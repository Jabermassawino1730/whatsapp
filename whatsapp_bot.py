import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from requests.exceptions import RequestException

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
API_ENDPOINT = os.getenv("API_ENDPOINT")  # Same endpoint as your Telegram bot
if not API_ENDPOINT:
    raise ValueError("API_ENDPOINT environment variable not set.")

# Twilio Credentials (OPTIONAL for sending proactive msgs; 
# not strictly required if only responding via TwiML)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

# Simple in-memory session store: { phone_number: session_data }
SESSION_STORE = {}

app = Flask(__name__)

@app.route("/whatsapp/webhook", methods=["POST"])
def whatsapp_webhook():
    """
    This endpoint receives incoming WhatsApp messages from Twilio 
    and responds using TwiML. It emulates similar behavior as the Telegram bot.
    """
    from_number = request.form.get("From")  # 'whatsapp:+1234567890'
    message_body = request.form.get("Body")  # User's text message
    latitude = request.form.get("Latitude")  # If location is sent
    longitude = request.form.get("Longitude")
    
    # Identify the user session by phone number
    session_id = from_number if from_number else "default_session"
    session_data = SESSION_STORE.get(session_id, {})
    first_name = session_data.get("first_name", "")  # We don't get first_name automatically from WhatsApp
    
    # Twilio Response object
    resp = MessagingResponse()
    
    # If we see location data
    if latitude and longitude:
        # The user sent a location via WhatsApp
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

            # Save session data
            SESSION_STORE[session_id] = session_data
            
            # Build outgoing message from GPT
            gpt_response = data.get("reply", "")
            # Add GPT response to Twilio message
            resp.message(gpt_response)

            # If products are mentioned
            mentioned_products = data.get("mentioned_products", [])
            for product in mentioned_products:
                # Send product info
                product_title = product["title"]
                product_desc = product["description"]
                # Instead of inline buttons, we’ll prompt the user:
                # "Reply: DETAILS {product_title} for more"
                product_msg = (
                    f"*{product_title}*\n{product_desc}\n"
                    f"Reply with: DETAILS {product_title} to see more."
                )
                resp.message(product_msg)

        except RequestException as e:
            logger.error(f"API request failed: {e}")
            resp.message("Sorry, I'm having trouble connecting to the server. Please try again later.")

    else:
        # No location; treat the message as text
        if not message_body:
            # If there's absolutely no text, respond politely
            resp.message("Hello! Please send your query or location.")
            return str(resp)
        
        # Check if user requested product details
        # We look for messages like: "DETAILS ProductName"
        if message_body.strip().upper().startswith("DETAILS"):
            # The user wants more info about a specific product
            try:
                # e.g. "DETAILS Tractor" => product_title = "Tractor"
                parts = message_body.split(" ", 1)  # split once
                if len(parts) == 2:
                    requested_product = parts[1].strip()
                    response_text = get_product_details(requested_product)
                    resp.message(response_text)
                else:
                    resp.message("Please specify which product details you want. Example: DETAILS Tractor")
            except Exception as ex:
                logger.error(f"Error retrieving product details: {ex}")
                resp.message("Could not retrieve product details at the moment. Try again later.")

        else:
            # Normal user message -> forward to API
            payload = {
                "session_id": session_id,
                "message": message_body,
                "first_name": first_name
            }
            try:
                api_response = requests.post(API_ENDPOINT, json=payload)
                api_response.raise_for_status()
                data = api_response.json()

                # Save session data
                SESSION_STORE[session_id] = session_data

                gpt_response = data.get("reply", "")
                resp.message(gpt_response)

                # If products are mentioned
                mentioned_products = data.get("mentioned_products", [])
                for product in mentioned_products:
                    product_title = product["title"]
                    product_desc = product["description"]
                    product_msg = (
                        f"*{product_title}*\n{product_desc}\n"
                        f"Reply with: DETAILS {product_title} to see more."
                    )
                    resp.message(product_msg)

            except RequestException as e:
                logger.error(f"API request failed: {e}")
                resp.message("Sorry, I'm having trouble connecting to the server. Please try again later.")
    
    return str(resp)

def get_product_details(product_title):
    """
    Mimics the callback query logic from the Telegram bot.
    Loads the JSON file, finds the product, returns a details string.
    """
    try:
        with open("company-information.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            products = data.get("products", [])

        # Case-insensitive match
        product = next((p for p in products if p["title"].lower() == product_title.lower()), None)
        if product:
            detailed_description = product.get('detailed_description', {})
            details_str = parse_detailed_description(detailed_description)
            
            # Build the final message
            response = (
                f"*{product['title']}*\n"
                f"{product['description']}\n\n"
                f"{details_str}\n"
                f"View Product: {product.get('product_url', 'No URL')}"
            )
            return response
        else:
            return f"Sorry, I couldn't find details for the product '{product_title}'."
    except Exception as e:
        logger.error(f"Error reading product data: {e}")
        return "Error loading product details. Please try again later."

def parse_detailed_description(detailed_desc):
    """
    Convert a nested dict/list structure into user-friendly text (like the Telegram version).
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
