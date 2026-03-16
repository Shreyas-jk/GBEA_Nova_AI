"""Document reader tool — extracts eligibility-relevant info from uploaded documents."""

from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from strands import Agent, tool
from strands.models import BedrockModel

from config import AWS_REGION, MODEL_ID, MAX_TOKENS, TEMPERATURE

DOCUMENT_ANALYSIS_PROMPT = """\
You are a document analyst for BenefitsNavigator. Extract any information \
relevant to government benefits eligibility from this document.

Look for and extract:
- Income amounts (gross pay, net pay, annual salary, hourly wage)
- Employer name and employment status
- Pay period and frequency
- Household members / dependents listed
- Addresses (city, state, zip)
- Rent or mortgage amounts
- Utility costs
- Tax filing status
- Number of dependents / children
- Any government program references (SNAP, Medicaid, etc.)
- Dates (pay dates, lease dates, tax year)

Return a JSON object with ONLY the fields you can confidently identify. \
Use null for fields you cannot determine. Use these field names where applicable:
- annual_income (int, in dollars — annualize if given a pay stub)
- employer_name (str)
- employment_status (str)
- state (2-letter code)
- household_size (int)
- rent_amount (int, monthly)
- has_children (bool)
- number_of_dependents (int)
- filing_status (str)
- document_type (str — what kind of document this appears to be)
- summary (str — brief human-readable summary of what was found)

Return ONLY valid JSON — no markdown fences, no extra text.
"""

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
_IMAGE_FORMAT_MAP = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".webp": "webp",
    ".bmp": "png",
    ".tiff": "png",
}


def _extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        return "[Error: pdfplumber not installed. Run: pip install pdfplumber]"

    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages[:20]):  # Limit to 20 pages
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

            # Also extract tables
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    cells = [str(c) if c else "" for c in row]
                    text_parts.append(" | ".join(cells))

    return "\n\n".join(text_parts) if text_parts else "[No text could be extracted from this PDF]"


def _analyze_image_with_nova(file_path: str) -> str:
    """Send an image to Nova 2 Lite for multimodal analysis."""
    ext = os.path.splitext(file_path)[1].lower()
    img_format = _IMAGE_FORMAT_MAP.get(ext, "png")

    with open(file_path, "rb") as f:
        image_bytes = f.read()

    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    response = bedrock.converse(
        modelId="us.amazon.nova-2-lite-v1:0",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": img_format,
                            "source": {"bytes": image_bytes},
                        }
                    },
                    {
                        "text": (
                            "This is a document uploaded by someone seeking government benefits. "
                            "Extract ALL text and numbers visible in this image. "
                            "Pay special attention to: dollar amounts, names, addresses, dates, "
                            "employer information, income figures, and any government program references."
                        ),
                    },
                ],
            }
        ],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE},
    )

    result = response["output"]["message"]["content"]
    return " ".join(block.get("text", "") for block in result)


def _analyze_text_with_agent(text: str, doc_type: str) -> str:
    """Send extracted text to a sub-agent for structured extraction."""
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        streaming=False,
    )

    agent = Agent(model=model, system_prompt=DOCUMENT_ANALYSIS_PROMPT)

    prompt = f"Document type hint: {doc_type}\n\nExtracted text:\n{text[:8000]}"
    result = agent(prompt)
    return str(result)


@tool
def analyze_document(file_path: str, document_type: str = "unknown") -> str:
    """Analyze an uploaded document to extract information relevant to benefits eligibility.

    Supports pay stubs, tax returns (W-2, 1099), lease agreements, utility bills,
    ID documents, and other documents that may contain income, residency, or
    household information.

    Args:
        file_path: Path to the uploaded file (PDF or image).
        document_type: Type hint — pay_stub, tax_return, lease, utility_bill, id, or unknown.

    Returns:
        str: JSON with extracted information relevant to benefits eligibility.
    """
    if not os.path.exists(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})

    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == ".pdf":
            extracted_text = _extract_text_from_pdf(file_path)
            raw_analysis = _analyze_text_with_agent(extracted_text, document_type)
        elif ext in _IMAGE_EXTENSIONS:
            # Use Nova multimodal for images
            image_text = _analyze_image_with_nova(file_path)
            raw_analysis = _analyze_text_with_agent(image_text, document_type)
        else:
            return json.dumps({"error": f"Unsupported file type: {ext}. Supported: PDF, PNG, JPG, JPEG"})

        # Try to parse as JSON
        cleaned = raw_analysis.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            parsed = json.loads(cleaned)
            return json.dumps(parsed, indent=2)
        except json.JSONDecodeError:
            return json.dumps({
                "raw_analysis": raw_analysis,
                "document_type": document_type,
                "note": "Could not parse structured data; raw analysis provided above.",
            }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Document analysis failed: {str(e)}"})
