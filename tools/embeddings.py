"""Nova Multimodal Embedding client — uses Amazon Nova Embed via Bedrock."""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from config import AWS_REGION

log = logging.getLogger("benefits-embed")

EMBED_MODEL_ID = "amazon.nova-embed-multimodal-v1:0"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    return _client


def generate_embedding(text: str) -> list[float]:
    """Generate an embedding vector for the given text using Nova Multimodal Embedding.

    Args:
        text: The text to embed (max ~1024 tokens recommended).

    Returns:
        A list of floats representing the embedding vector.
    """
    client = _get_client()
    response = client.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text}),
    )
    result = json.loads(response["body"].read())
    return result["embedding"]
