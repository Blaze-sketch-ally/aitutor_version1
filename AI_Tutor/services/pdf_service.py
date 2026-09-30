from fpdf import FPDF


class PDFService:

    def create_pdf(
        self,
        title: str,
        content: str,
        output_path: str
    ):

        pdf = FPDF()

        pdf.add_page()

        pdf.set_font(
            "Arial",
            size=12
        )

        pdf.cell(
            200,
            10,
            txt=title,
            ln=True,
            align="C"
        )

        pdf.multi_cell(
            0,
            10,
            content
        )

        pdf.output(output_path)

        return output_path