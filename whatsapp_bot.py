# whatsapp_bot.py
import os
import json
import logging
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from requests.exceptions import RequestException

# Logging Configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
API_ENDPOINT = os.getenv("API_ENDPOINT")  # Same endpoint as your Telegram bot
if not API_ENDPOINT:
    raise ValueError("API_ENDPOINT environment variable not set.")

# OPTIONAL Twilio credentials (only needed if you want to send proactive messages)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

# In-memory session: { phone_number: {some data} }
SESSION_STORE = {}

app = Flask(__name__)

@app.route("/whatsapp/webhook", methods=["POST"])
def whatsapp_webhook():
    """
    Main webhook endpoint for incoming WhatsApp messages via Twilio.
    """
    from_number = request.form.get("From")  # e.g. 'whatsapp:+1234567890'
    message_body = request.form.get("Body")  # User's text
    latitude = request.form.get("Latitude")  # Location fields if user shares location
    longitude = request.form.get("Longitude")

    # Identify user session by phone number
    session_id = from_number if from_number else "default_session"
    session_data = SESSION_STORE.get(session_id, {})
    first_name = session_data.get("first_name", "")  # We don't auto-get a name from WhatsApp

    # Twilio MessagingResponse
    resp = MessagingResponse()

    # LOCATION handling (user shares location)
    if latitude and longitude:
        # Prepare payload for the chatbot API
        payload = {
            "session_id": session_id,
            "message": "Here is my location.",
            "first_name": first_name,
            "location": {
                "latitude": float(latitude),
                "longitude": float(longitude)
            }
        }
        try:
            api_response = requests.post(API_ENDPOINT, json=payload)
            api_response.raise_for_status()
            data = api_response.json()

            # Update session data if needed
            SESSION_STORE[session_id] = session_data

            # Build GPT response
            gpt_response = data.get("reply", "")
            resp.message(gpt_response)

            # If any products are mentioned, attach them with images
            mentioned_products = data.get("mentioned_products", [])
            for product in mentioned_products:
                product_title = product["title"]
                product_desc = product["description"]
                image_url = product.get("image_link", product.get("link", ""))

                product_msg = (
                    f"*{product_title}*\n{product_desc}\n"
                    f"Reply with: DETAILS {product_title} to see more."
                )
                msg = resp.message(product_msg)
                if image_url:
                    msg.media(image_url)

        except RequestException as e:
            logger.error(f"API request failed: {e}")
            resp.message("Sorry, I'm having trouble connecting to the server. Please try again later.")

    else:
        # TEXT handling
        if not message_body:
            # No text provided
            resp.message("Hello! Please send your query or location.")
            return str(resp)

        # Check if user requested details for a product: "DETAILS ProductName"
        if message_body.strip().upper().startswith("DETAILS"):
            parts = message_body.split(" ", 1)  # split into ["DETAILS", "ProductName..."]
            if len(parts) == 2:
                requested_product = parts[1].strip()
                response_text = get_product_details(requested_product)
                resp.message(response_text)
            else:
                resp.message("Please specify which product details you want, e.g. DETAILS Tractor")
        else:
            # Normal user message => forward to the chatbot API
            payload = {
                "session_id": session_id,
                "message": message_body,
                "first_name": first_name
            }
            try:
                api_response = requests.post(API_ENDPOINT, json=payload)
                api_response.raise_for_status()
                data = api_response.json()

                SESSION_STORE[session_id] = session_data

                gpt_response = data.get("reply", "")
                resp.message(gpt_response)

                # If products are mentioned, attach them with images
                mentioned_products = data.get("mentioned_products", [])
                for product in mentioned_products:
                    product_title = product["title"]
                    product_desc = product["description"]
                    image_url = product.get("image_link", product.get("link", ""))

                    product_msg = (
                        f"*{product_title}*\n{product_desc}\n"
                        f"Reply with: DETAILS {product_title} to see more."
                    )
                    msg = resp.message(product_msg)
                    if image_url:
                        msg.media(image_url)

            except RequestException as e:
                logger.error(f"API request failed: {e}")
                resp.message("Sorry, I'm having trouble connecting to the server. Please try again later.")

    return str(resp)


def get_product_details(product_title: str) -> str:
    """
    Loads 'company-information.json', finds the requested product, returns a details string.
    Similar logic to the Telegram callback query approach.
    """
    try:
        with open("company-information.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            products = data.get("products", [])

        # Find product by matching title (case-insensitive)
        product = next((p for p in products if p["title"].lower() == product_title.lower()), None)
        if product:
            details_str = parse_detailed_description(product.get("detailed_description", {}))
            response = (
                f"*{product['title']}*\n{product['description']}\n\n"
                f"{details_str}\n"
                f"View Product: {product.get('product_url', 'No URL available')}"
            )
            return response
        else:
            return f"Sorry, I couldn't find details for '{product_title}'."
    except Exception as e:
        logger.error(f"Error loading product details: {e}")
        return "Error loading product details. Please try again later."


def parse_detailed_description(detailed_desc) -> str:
    """
    Converts nested dict or list to user-friendly text lines.
    """
    if isinstance(detailed_desc, dict):
        final_str = ""
        for key, value in detailed_desc.items():
            if isinstance(value, dict):
                specs = "\n".join([f"  - {sub_key}: {sub_val}" for sub_key, sub_val in value.items()])
                final_str += f"*{key}:*\n{specs}\n"
            elif isinstance(value, list):
                specs = "\n".join([f"  - {item}" for item in value])
                final_str += f"*{key}:*\n{specs}\n"
            else:
                final_str += f"*{key}:* {value}\n"
        return final_str
    elif isinstance(detailed_desc, list):
        return "\n".join([f"  - {item}" for item in detailed_desc])
    elif isinstance(detailed_desc, str):
        return detailed_desc
    else:
        return "No detailed description available."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
