from huggingface_hub import InferenceClient
from dotenv import load_dotenv
import os

load_dotenv()

client = InferenceClient(
    token=os.getenv("HF_TOKEN")
)

def generate(
    prompt: str,
    model: str = "Qwen/Qwen2.5-7B-Instruct",
    max_new_tokens: int = 512
):
    """
    Generate text using Hugging Face models.
    """

    response = client.text_generation(
        prompt,
        model=model,
        max_new_tokens=max_new_tokens
    )

    return response