import json
import re
import math
import urllib.parse

from langsmith import traceable
from models.router import route
from models.errors import LLMServiceError


# ==================================================
# KEYWORD HINTS (cheap first pass, same pattern as
# YouTubeAgent._detect_duration_preference)
# ==================================================

# All hints are WHOLE-WORD regexes. Plain substring matching used to
# send "flowchart" to the chart path ("chart" inside "flowchart"),
# "photograph"/"paragraph" to charts ("graph"), and "draw a flowchart"
# to the external image service ("draw a" was an image hint checked
# first).
#
# Priority (first match wins):
#   1. structural diagram names  -> mermaid   (flowchart, sequence
#      diagram, architecture diagram, ...) — unambiguous, so they beat
#      "draw"/"image"/"chart" words in the same request
#   2. math function / equation  -> math_chart (values computed, never
#      LLM-guessed)
#   3. data chart / graph words  -> chart
#   4. picture / image words     -> image
#   5. generic "diagram"/"architecture"/"hierarchy" -> mermaid
#   6. nothing                   -> None (LLM classifier decides)


def _words(*patterns: str) -> re.Pattern:

    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b")


_STRONG_MERMAID_RE = _words(
    r"flow ?charts?", r"sequence diagrams?", r"class diagrams?",
    r"state (?:machine )?diagrams?", r"er diagrams?",
    r"entity[- ]relationship", r"mind ?maps?", r"block diagrams?",
    r"process flows?", r"workflows?", r"data ?flow diagrams?",
    r"(?:architecture|architectural|system|network|component|"
    r"deployment|process|pipeline) diagrams?",
    r"mermaid", r"gantt"
)

_MATH_GRAPH_RE = _words(
    r"parabolas?", r"parabolic", r"quadratic", r"equations?",
    r"function graphs?", r"(?:sine|cosine|tangent) (?:wave|curve)s?",
    r"trigonometric graphs?", r"graph of the (?:function|equation)"
)

_CHART_RE = _words(
    r"charts?", r"graphs?", r"plot", r"plots", r"histograms?",
    r"scatter ?plots?", r"statistics", r"stats", r"trends?",
    r"data visuali[sz]ations?", r"visuali[sz]e (?:the )?data"
)

_IMAGE_RE = _words(
    r"pictures?", r"images?", r"illustrations?", r"illustrate",
    r"photos?", r"photographs?", r"artworks?", r"art of",
    r"posters?", r"drawings?", r"draw", r"sketch(?:es)?", r"paintings?",
    r"wallpapers?", r"logos?"
)

_WEAK_MERMAID_RE = _words(
    r"diagrams?", r"architecture", r"hierarchy", r"hierarchies",
    r"org ?chart", r"timeline", r"lifecycle", r"life cycle"
)


def _keyword_type(query: str):

    text = query.lower()

    if _STRONG_MERMAID_RE.search(text):
        return "mermaid"

    if _MATH_GRAPH_RE.search(text) or _looks_like_equation(text):
        return "math_chart"

    # "org chart" is a hierarchy (mermaid), not a data chart.
    if _CHART_RE.search(text) and not re.search(r"\borg ?charts?\b", text):
        return "chart"

    if _IMAGE_RE.search(text):
        return "image"

    if _WEAK_MERMAID_RE.search(text):
        return "mermaid"

    return None


# ==================================================
# MERMAID SANITIZING
# ==================================================
# LLM-written Mermaid regularly breaks the parser with labels such as
# C[Client: SEAL (128-bit nonce)] — unquoted (), [], {}, quotes, etc.
# inside a node label end the shape early. For flowcharts every node
# and edge label is re-emitted as a quoted string ("..." with inner
# quotes as #quot;), which Mermaid accepts for any text. Other diagram
# types only get the light-touch fixes below.

_MERMAID_HEADERS = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram",
    "stateDiagram", "stateDiagram-v2", "erDiagram", "gantt", "pie",
    "mindmap", "journey", "timeline", "gitGraph", "quadrantChart"
)

# Longest openers first so "[[" isn't read as "[".
_NODE_SHAPES = (
    ("(((", ")))"), ("[[", "]]"), ("[(", ")]"), ("((", "))"),
    ("([", "])"), ("{{", "}}"), ("[", "]"), ("(", ")"), ("{", "}"),
    (">", "]"),
)

_NODE_START_RE = re.compile(
    r"([A-Za-z_][\w]*)("
    + "|".join(re.escape(opener) for opener, _ in _NODE_SHAPES)
    + r")"
)

# What may legally follow a node shape: end of line, a link, "&",
# a class suffix, a statement separator.
_AFTER_NODE_RE = re.compile(r"\s*($|;|&|:::|--|-\.|==|~~|<-|<=|o--|x--)")

_FLOWCHART_SKIP_RE = re.compile(
    r"^\s*(%%|classDef\b|class\b|style\b|linkStyle\b|click\b|direction\b)"
)


def _quote_label(label: str) -> str:

    text = label.strip()

    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]

    text = text.replace('"', "#quot;")

    return f'"{text}"'


def _quote_flowchart_line(line: str) -> str:

    if _FLOWCHART_SKIP_RE.match(line):
        return line

    out = []
    i = 0
    n = len(line)

    while i < n:

        ch = line[i]

        # Already-quoted text: copy through untouched.
        if ch == '"':
            j = line.find('"', i + 1)
            j = n - 1 if j == -1 else j
            out.append(line[i:j + 1])
            i = j + 1
            continue

        # Edge label: -->|text|
        if ch == "|":
            j = line.find("|", i + 1)
            if j != -1:
                out.append("|" + _quote_label(line[i + 1:j]) + "|")
                i = j + 1
                continue

        at_token_start = i == 0 or not (line[i - 1].isalnum() or line[i - 1] == "_")
        match = _NODE_START_RE.match(line, i) if at_token_start else None

        if match:

            node_id, opener = match.group(1), match.group(2)
            closer = dict(_NODE_SHAPES)[opener]
            label_start = match.end()

            # The label ends at the first closer that is followed by
            # something that can legally follow a node — so ")" inside
            # "SEAL (128-bit nonce)]" doesn't end a "[" label.
            k = label_start
            end = None

            while True:
                k = line.find(closer, k)
                if k == -1:
                    break
                if _AFTER_NODE_RE.match(line, k + len(closer)):
                    end = k
                    break
                k += 1

            if end is not None and node_id not in ("end", "subgraph"):
                label = line[label_start:end]
                out.append(node_id + opener + _quote_label(label) + closer)
                i = end + len(closer)
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def sanitize_mermaid(code: str) -> str:

    text = (code or "").strip()

    # Fences, with or without a language tag.
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text).strip()

    lines = text.splitlines()

    # Drop any prose before the diagram header.
    start = next(
        (
            idx for idx, line in enumerate(lines)
            if line.strip().split(" ")[0] in _MERMAID_HEADERS
        ),
        None
    )

    if start is None:
        lines = ["flowchart TD"] + lines
        start = 0

    lines = lines[start:]
    header = lines[0].strip().split(" ")[0]

    if header in ("flowchart", "graph"):

        lines = [lines[0]] + [_quote_flowchart_line(l) for l in lines[1:]]

    elif header == "sequenceDiagram":

        # ";" ends a statement in sequence diagrams — keep message text
        # after the first ":" in one piece.
        fixed = []
        for line in lines:
            head, sep, message = line.partition(":")
            if sep and ("->" in head or "--" in head):
                line = head + sep + message.replace(";", ",")
            fixed.append(line)
        lines = fixed

    return "\n".join(lines).strip()


# ==================================================
# CHART DATA GROUNDING
# ==================================================

# "A=10, B=20", "2019: 45", "Apples = 3.5" — label, then = or :, then
# a number. Labels may start with a letter or digit (years).
_VALUE_PAIR_RE = re.compile(
    r"(?<![\w.])([A-Za-z0-9][\w .\-/()']{0,40}?)\s*[=:]\s*(-?\d+(?:\.\d+)?)\s*%?(?![\w.])"
)

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def extract_explicit_values(text: str):
    """
    Returns (labels, values) when the request itself supplies at least
    two "label = value" pairs, else None. These are the user's own
    numbers, so they are charted as-is with no model involved.
    """

    pairs = []

    for label, value in _VALUE_PAIR_RE.findall(text or ""):

        label = label.strip(" ,;")

        # "values: A=10" — take the last word as the label.
        label = re.split(
            r"\b(?:values?|data|numbers?|using|with|of|are|is|charts?|"
            r"graphs?|plots?|diagrams?|and|or|plus|then)\b|&",
            label
        )[-1].strip(" ,;:")

        if not label or re.fullmatch(r"[xyf]|f\(x\)", label.lower()):
            continue

        number = float(value)
        pairs.append((label, int(number) if number.is_integer() else number))

    if len(pairs) < 2:
        return None

    return [p[0] for p in pairs], [p[1] for p in pairs]


def _numbers_in(text: str) -> set[float]:

    numbers = set()

    for raw in _NUMBER_RE.findall(text or ""):

        try:
            numbers.add(float(raw.replace(",", "")))
        except ValueError:
            pass

    return numbers


def _chart_values_are_grounded(data: dict, allowed: set[float]) -> bool:
    """Every plotted value must literally occur in the source text."""

    values = [
        v
        for dataset in data.get("datasets", [])
        for v in (dataset.get("data") or [])
    ]

    if len(values) < 2:
        return False

    for v in values:

        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return False

        if not any(abs(float(v) - a) <= 1e-9 * max(1.0, abs(a)) for a in allowed):
            print(f"DiagramAgent: rejected ungrounded chart value {v}")
            return False

    return True


def _requested_chart_type(text: str) -> str:

    lowered = (text or "").lower()

    for chart_type in ("doughnut", "pie", "line", "radar"):
        if re.search(r"\b" + chart_type + r"\b", lowered):
            return chart_type

    return "bar"


def _chart_title(text: str) -> str:

    title = re.split(r"[:.]", text or "", maxsplit=1)[0].strip()

    return title[:80] or "Chart"


def _looks_like_equation(text: str) -> bool:
    """Catches raw equation-style requests like 'y = x^2 + 3' or
    'plot x**2 - 4' even without an explicit keyword hint."""

    return bool(
        re.search(r"\by\s*=\s*[-\d x^*/+().]+", text)
        or re.search(r"\bf\(x\)\s*=", text)
    )


class DiagramAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    # ==================================================
    # PUBLIC ENTRY POINT
    # ==================================================

    @traceable(
        name="DiagramAgent.generate_diagram"
    )
    def generate_diagram(
        self,
        topic: str,
        context: str = "",
        history_text: str = "",
        summary: str = "",
        strict_pdf: bool = False
    ):
        """
        Returns a dict:
            {"type": "mermaid", "content": "<mermaid code>"}
            {"type": "chart",   "content": {chart_type, title, labels, datasets}}
            {"type": "image",   "content": "<image url>", "prompt": "<prompt used>"}
        """

        output_type = (
            _keyword_type(topic)
            or self._classify_type(
                topic=topic,
                history_text=history_text,
                summary=summary
            )
        )

        if output_type == "math_chart":

            return {
                "type": "chart",
                "content": self._generate_math_chart(
                    topic=topic,
                    history_text=history_text,
                    summary=summary
                )
            }

        if output_type == "chart":

            chart = self._generate_chart(
                topic=topic,
                context=context,
                history_text=history_text,
                summary=summary,
                strict_pdf=strict_pdf
            )

            if chart is None:

                # No trustworthy numbers: no chart. "none" is turned into
                # answer text by the Orchestrator (never rendered as a
                # diagram).
                return {
                    "type": "none",
                    "message": (
                        self.NO_CHART_DATA_MESSAGE
                        if (context.strip() or strict_pdf)
                        else self.NO_GENERAL_DATA_MESSAGE
                    )
                }

            return {
                "type": "chart",
                "content": chart
            }

        if output_type == "image":

            prompt = self._generate_image_prompt(
                topic=topic,
                context=context,
                history_text=history_text,
                summary=summary
            )

            return {
                "type": "image",
                "content": self._build_pollinations_url(prompt),
                "prompt": prompt
            }

        # Default / fallback
        return {
            "type": "mermaid",
            "content": self._generate_mermaid(
                topic=topic,
                context=context,
                history_text=history_text,
                summary=summary,
                strict_pdf=strict_pdf
            )
        }

    # ==================================================
    # STEP 0 — CLASSIFY OUTPUT TYPE (LLM fallback)
    # ==================================================

    def _classify_type(
        self,
        topic: str,
        history_text: str,
        summary: str
    ) -> str:

        prompt = f"""
Decide what kind of visual the user wants for their request.

Choose exactly ONE of:
- "mermaid"    -> flowcharts, processes, architecture, block diagrams,
                  relationships, hierarchies, sequences
- "chart"      -> bar/line/pie/doughnut charts plotting given/known
                  numeric data, comparisons, statistics, trends
- "math_chart" -> plotting a mathematical function or equation
                  (parabola, sine wave, y = f(x), etc.)
- "image"      -> a real illustration/picture/artwork/photo of a
                  person, place, or thing (not a data diagram)

==================================================
CONVERSATION SUMMARY
==================================================
{summary}

==================================================
CONVERSATION HISTORY
==================================================
{history_text}

==================================================
REQUEST
==================================================
{topic}

Return ONLY one lowercase word: mermaid, chart, or image.
"""

        try:

            result = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="extract"
            ).strip().lower()

            # Exact word match — "flowchart" must not read as "chart".
            word = re.sub(r"[^a-z_]", " ", result).split()

            for candidate in ("math_chart", "chart", "image", "mermaid"):
                if candidate in word:
                    return candidate

            return "mermaid"

        except Exception as e:

            print(f"DiagramAgent classify error: {e}")
            return "mermaid"

    # ==================================================
    # MERMAID GENERATION
    # ==================================================

    def _generate_mermaid(
        self,
        topic: str,
        context: str,
        history_text: str,
        summary: str,
        strict_pdf: bool
    ) -> str:

        rule_block = (
            """
You are an expert diagram generator.

RULES:
- Use ONLY PDF context.
- Use summary and history to resolve references.
- Do NOT use external knowledge.
"""
            if strict_pdf else
            """
Your are Athena , an AI Tutor.

RULES:
- Use PDF context if available.
- Use general knowledge if required.
- Use summary and history to resolve references.
- Generate educational diagrams.
"""
        )

        prompt = f"""
{rule_block}

==================================================
CONVERSATION SUMMARY
==================================================
{summary}

==================================================
CONVERSATION HISTORY
==================================================
{history_text}

==================================================
PDF CONTEXT
==================================================
{context}

==================================================
CURRENT REQUEST
==================================================
{topic}

==================================================
OUTPUT RULES
==================================================
- Output ONLY Mermaid code
- Use an appropriate Mermaid diagram type (flowchart TD, sequenceDiagram,
  classDiagram, stateDiagram-v2, mindmap, etc.) based on the request
- No markdown code fences
- No explanations
- No comments
- In flowcharts, put every node label in double quotes, e.g.
  A["Client sends SYN (seq = x)"] --> B["Server: SYN-ACK"]
- Never put double quotes or semicolons inside a label or message

Generate the diagram now.
"""

        result = route(
            prompt=prompt,
            provider=self.provider,
            model=self.model,
            purpose="diagram"
        )

        return sanitize_mermaid(result)

    # ==================================================
    # CHART GENERATION (structured JSON -> Chart.js)
    # ==================================================
    # Charts must never show invented numbers. Where the data comes
    # from decides what is allowed:
    #   1. explicit "label = value" pairs in the request -> charted
    #      directly, no LLM involved;
    #   2. document/image context present -> the LLM may only EXTRACT
    #      numbers, and every number it returns must literally occur in
    #      the context or the request (verified here, not trusted);
    #   3. a PDF-only (strict) request with no context -> no chart;
    #   4. no document involved -> well-established public figures
    #      only, labelled as approximate general knowledge, and the
    #      model must decline when it has no real data.
    # Returns None when no trustworthy data exists; generate_diagram()
    # turns that into NO_CHART_DATA_MESSAGE instead of a chart.

    NO_CHART_DATA_MESSAGE = (
        "I couldn't find enough numerical data in the selected material "
        "to create this chart."
    )

    NO_GENERAL_DATA_MESSAGE = (
        "I don't have reliable numbers for this chart. If you share the "
        "values (for example \"A=10, B=20\") or select a PDF that "
        "contains them, I'll chart them."
    )

    def _generate_chart(
        self,
        topic: str,
        context: str,
        history_text: str,
        summary: str,
        strict_pdf: bool
    ) -> dict | None:

        explicit = extract_explicit_values(topic)

        if explicit:

            labels, values = explicit

            return {
                "chart_type": _requested_chart_type(topic),
                "title": _chart_title(topic),
                "labels": labels,
                "datasets": [{"label": "Value", "data": values}]
            }

        if context.strip():

            data = self._chart_from_llm(
                topic=topic,
                context=context,
                history_text=history_text,
                summary=summary,
                source_rule=(
                    "Use ONLY numbers that appear in the SOURCE MATERIAL "
                    "or in the request itself. Never estimate, round, "
                    "interpolate or invent a value. If the material "
                    "doesn't contain at least two relevant numbers, "
                    "return {\"insufficient_data\": true}."
                )
            )

            allowed = _numbers_in(context) | _numbers_in(topic)

            if data is None or not _chart_values_are_grounded(data, allowed):
                return None

            return data

        if strict_pdf:
            return None

        data = self._chart_from_llm(
            topic=topic,
            context="",
            history_text=history_text,
            summary=summary,
            source_rule=(
                "No document is involved. Use ONLY well-established, "
                "widely published figures you are confident about. Do "
                "NOT make up illustrative or example numbers. If you "
                "don't know real figures for this request, return "
                "{\"insufficient_data\": true}."
            )
        )

        if data is None:
            return None

        data["title"] = (
            f"{data.get('title') or _chart_title(topic)} "
            "(approximate, general knowledge — not from your material)"
        )

        return data

    def _chart_from_llm(
        self,
        topic: str,
        context: str,
        history_text: str,
        summary: str,
        source_rule: str
    ) -> dict | None:

        prompt = f"""
You are a data visualization assistant for an AI Tutor.

SOURCE RULE: {source_rule}

The conversation below is ONLY for resolving references like "that" or
"it". It is NOT a source of numbers.

==================================================
CONVERSATION SUMMARY (not a data source)
==================================================
{summary}

==================================================
CONVERSATION HISTORY (not a data source)
==================================================
{history_text}

==================================================
SOURCE MATERIAL
==================================================
{context or "(none)"}

==================================================
CURRENT REQUEST
==================================================
{topic}

==================================================
OUTPUT FORMAT — RETURN ONLY THIS JSON, NOTHING ELSE
==================================================
{{
  "chart_type": "bar",
  "title": "Short descriptive title",
  "labels": ["Label1", "Label2", "..."],
  "datasets": [
    {{"label": "Series name", "data": [1, 2, 3]}}
  ]
}}
or, when the rule above can't be met:
{{"insufficient_data": true}}

RULES:
- chart_type must be one of: bar, line, pie, doughnut, radar
- Use "pie" or "doughnut" only for a single dataset of proportions
- Keep labels and datasets the same length
- Return ONLY valid JSON, no markdown fences, no explanation
"""

        try:

            raw = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="chart"
            )

            data = self._extract_json(raw)

        except LLMServiceError:

            # Provider failure — let the API report it instead of
            # returning a canned apology as if it were content.
            raise

        except Exception as e:

            print(f"DiagramAgent chart error: {e}")
            return None

        if data.get("insufficient_data"):
            return None

        data.setdefault("chart_type", _requested_chart_type(topic))
        data.setdefault("title", _chart_title(topic))
        data.setdefault("labels", [])
        data.setdefault("datasets", [])

        values = [
            v
            for dataset in data["datasets"]
            for v in (dataset.get("data") or [])
        ]

        if len(values) < 2 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in values
        ):
            return None

        return data

    # ==================================================
    # MATH GRAPH GENERATION (real computed values, not LLM-guessed)
    # ==================================================

    _SAFE_NAMES = {
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
        "exp": math.exp, "abs": abs, "pow": pow,
        "pi": math.pi, "e": math.e
    }

    def _generate_math_chart(
        self,
        topic: str,
        history_text: str,
        summary: str
    ) -> dict:

        # Step 1: ask the LLM ONLY to extract the equation + a sensible
        # x-range as JSON — no arithmetic required from it at all.
        prompt = f"""
Extract the mathematical function and a sensible x-axis range for
plotting, based on this request. Use history/summary to resolve
references like "it" or "that equation".

==================================================
CONVERSATION SUMMARY
==================================================
{summary}

==================================================
CONVERSATION HISTORY
==================================================
{history_text}

==================================================
REQUEST
==================================================
{topic}

Return ONLY this JSON (no markdown fences, no explanation):
{{
  "expression": "x**2",
  "title": "y = x^2",
  "x_min": -10,
  "x_max": 10
}}

RULES:
- "expression" must be valid Python using variable x and, if needed,
  the functions sin, cos, tan, sqrt, log, log10, exp, abs, pow, pi, e
- Use ** for powers (never ^)
- Pick x_min/x_max that show the interesting part of the curve
  (e.g. a couple of periods for trig functions, vertex-centered for
  parabolas)
"""

        try:

            raw = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="extract"
            )

            spec = self._extract_json(raw)

            expression = spec.get("expression", "x**2").replace("^", "**")
            title = spec.get("title", topic)
            x_min = float(spec.get("x_min", -10))
            x_max = float(spec.get("x_max", 10))

            if x_min >= x_max:
                x_min, x_max = -10, 10

            steps = 60
            step_size = (x_max - x_min) / steps

            labels = []
            data = []

            for i in range(steps + 1):

                x = x_min + i * step_size

                try:
                    y = eval(
                        expression,
                        {"__builtins__": {}},
                        {**self._SAFE_NAMES, "x": x}
                    )
                except Exception:
                    y = None

                labels.append(round(x, 2))
                data.append(round(y, 4) if isinstance(y, (int, float)) else None)

            return {
                "chart_type": "line",
                "title": title,
                "labels": labels,
                "datasets": [
                    {"label": title, "data": data}
                ]
            }

        except LLMServiceError:

            # Provider failure — let the API report it instead of
            # returning a canned apology as if it were content.
            raise

        except Exception as e:

            print(f"DiagramAgent math_chart error: {e}")

            return {
                "chart_type": "line",
                "title": f"Could not plot: {topic}",
                "labels": [],
                "datasets": []
            }

    # ==================================================
    # IMAGE PROMPT GENERATION
    # ==================================================

    def _generate_image_prompt(
        self,
        topic: str,
        context: str,
        history_text: str,
        summary: str
    ) -> str:

        # The result goes to a PUBLIC third-party service (Pollinations)
        # inside a URL, so the uploaded PDF's text is deliberately NOT
        # given to this step (the `context` argument is unused), and
        # the model is told not to copy specifics from the conversation.
        # History/summary are still passed only to resolve "it"/"that".
        prompt = f"""
Write a single, vivid, descriptive prompt (max 40 words) for an
AI image generator to illustrate the following educational request.
Use conversation summary/history ONLY to work out what "it"/"that"
refers to.

PRIVACY: this prompt is sent to a public image service. Describe the
generic visual subject only. Do NOT include names of people or
organisations from the conversation, numbers, codes, quotes, or any
other specific details from the student's documents or messages.

Style guidance: clean, educational, textbook-illustration style,
unless the request implies otherwise.

==================================================
CONVERSATION SUMMARY
==================================================
{summary}

==================================================
CONVERSATION HISTORY
==================================================
{history_text}

==================================================
REQUEST
==================================================
{topic}

Return ONLY the image prompt text, nothing else.
"""

        try:

            result = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="extract"
            ).strip()

            return result if result else topic

        except Exception as e:

            print(f"DiagramAgent image prompt error: {e}")
            return topic

    # ==================================================
    # POLLINATIONS.AI URL BUILDER (free, no API key)
    # ==================================================

    def _build_pollinations_url(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 768
    ) -> str:

        encoded_prompt = urllib.parse.quote(prompt)

        return (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&nologo=true"
        )

    # ==================================================
    # HELPERS
    # ==================================================

    @staticmethod
    def _strip_fences(text: str) -> str:

        cleaned = text.strip()

        if cleaned.startswith("```"):

            cleaned = cleaned.strip("`")

            # Drop a leading language tag like "mermaid" or "json"
            first_line, _, rest = cleaned.partition("\n")

            if first_line.strip().isalpha():
                cleaned = rest

        return cleaned.strip()

    @classmethod
    def _extract_json(cls, text: str) -> dict:
        """
        Robustly pulls a JSON object out of an LLM response.

        Small/fast models (e.g. llama-3.3-70b-versatile via Groq) very
        often ignore "return ONLY JSON" instructions and wrap the JSON
        in prose ("Here's the JSON:\n{...}", "Sure! {...}\nLet me know
        if..."), or still fence it in ``` even when told not to. A
        plain json.loads(strip_fences(text)) then throws
        "Expecting value: line 1 column 1", which was silently sending
        every math_chart / chart request into the empty-fallback path.

        This first tries the fast path (fence-stripped full string is
        valid JSON), then falls back to locating the first '{' and the
        matching last '}' in the text and parsing that substring.
        """

        cleaned = cls._strip_fences(text)

        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            pass

        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start != -1 and end != -1 and end > start:

            candidate = cleaned[start:end + 1]

            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Could not parse JSON from model output: {e}\n"
                    f"Raw output was: {text!r}"
                )

        raise ValueError(
            f"No JSON object found in model output.\nRaw output was: {text!r}"
        )