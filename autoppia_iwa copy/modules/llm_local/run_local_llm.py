import argparse
import gc
import logging

from flask import Flask, request
from flask_cors import CORS
from transformers import AutoModelForCausalLM, AutoTokenizer

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# -----------------------------------------------------------------------------
# REPLACE THE MODEL NAME WITH A Qwen/Qwen2.5-3B-Instruct
# -----------------------------------------------------------------------------
MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"

logger.info(f"Loading the tokenizer and model from '{MODEL_NAME}'...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME)
# If you have a GPU available, uncomment the next line:
model.to("cuda")
model.eval()


def generate_data(
    message_payload: str,
    max_new_tokens: int = 256,
    generation_kwargs: dict = None,
) -> str:
    if generation_kwargs is None:
        generation_kwargs = {}

    try:
        # Prepare the input tensor
        inputs = tokenizer(message_payload, return_tensors="pt")
        # Move them to GPU
        inputs = {k: v.to("cuda") for k, v in inputs.items()}

        # Generate text
        output_tokens = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            **generation_kwargs
        )

        # Decode the output
        output_text = tokenizer.decode(output_tokens[0], skip_special_tokens=True)

        return output_text

    except Exception as e:
        logger.error(f"Error generating data: {e}")
        return f"Generation error: {e}"

    finally:
        gc.collect()


@app.route("/generate", methods=["POST"])
def handler():
    """
    Handle incoming POST requests to generate data using the model.

    Expects JSON of the form:
    {
       "input": {
           "text": "Your prompt here",
           "ctx": 256,
           "generation_kwargs": {...}
       }
    }
    """
    try:
        inputs = request.json
        message_payload = inputs.get("input", {}).get("text", "")
        if not message_payload:
            raise ValueError("Input 'text' is missing or empty")

        max_new_tokens = int(inputs.get("input", {}).get("ctx", 256))
        generation_kwargs = inputs.get("input", {}).get("generation_kwargs", {})

        output = generate_data(
            message_payload=message_payload,
            max_new_tokens=max_new_tokens,
            generation_kwargs=generation_kwargs,
        )
        return {"output": output}

    except ValueError as ve:
        logger.error(f"Invalid input value: {ve}")
        return {"error": str(ve)}, 400
    except Exception as e:
        logger.error(f"Error handling event: {e}")
        return {"error": str(e)}, 500


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Hugging Face LLM service.")
    parser.add_argument("--port", type=int, default=6000, help="Port to run the service on")
    args = parser.parse_args()

    app.run(host="0.0.0.0", port=args.port, debug=True)
