import os
import logging
import requests
from flask import Flask, request, jsonify, make_response
from twilio.twiml.messaging_response import MessagingResponse

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Your API endpoint URL
API_ENDPOINT = os.getenv("API_ENDPOINT")  # e.g. "https://your-api.herokuapp.com/api/message"
if not API_ENDPOINT:
    raise ValueError("API_ENDPOINT environment variable not set.")

# In-memory session store: { "<user_number>": {"session_id": ..., "first_name": ..., ...} }
session_store = {}

def get_session_data(user_number):
    if user_number not in session_store:
        session_store[user_number] = {}
    return session_store[user_number]

@app.route("/whatsapp", methods=['POST'])
def whatsapp_webhook():
    # Twilio sends multiple fields, the most important are 'From' and 'Body'
    # 'From' is the sender's number in WhatsApp format: "whatsapp:+123456789"
    # 'Body' is the user's message text.
    from_number = request.form.get('From', '')
    user_message = request.form.get('Body', '').strip()
    latitude = request.form.get('Latitude', None)
    longitude = request.form.get('Longitude', None)

    # Extract a simpler user ID from the WhatsApp number
    user_id = from_number.replace("whatsapp:", "")

    session_data = get_session_data(user_id)
    # Assume first_name as the user’s number or can ask user their name at start
    if 'first_name' not in session_data:
        # Extract a simple name from their number or prompt them to set a name
        # For simplicity, use their phone number as their name.
        session_data['first_name'] = user_id

    # If user sends location, Twilio provides Latitude and Longitude in form fields.
    # If not provided, they'll be None.
    payload = {
        'session_id': user_id,
        'first_name': session_data['first_name']
    }

    # Check if user_message corresponds to product detail requests.
    # The Telegram bot had inline buttons, but we rely on user typing product name.
    # If we previously mentioned products, we told the user to reply with product title.
    # We assume if user_message matches a known product title, we request details.
    # However, we must differentiate between normal messages and product detail requests.
    # We'll do a product detail request if we detect the product in the product catalog after the user asked for details.

    # We'll attempt a product detail request only if:
    # 1. The user last received product suggestions.
    # 2. The user's message matches one of the mentioned products from the last message.
    mentioned_products = session_data.get('last_mentioned_products', [])

    # Check if user wants product detail
    request_type = 'message'
    product_title_requested = None
    if mentioned_products:
        # Normalize input and check against known products
        user_lower = user_message.lower()
        for p in mentioned_products:
            if p['title'].lower() == user_lower:
                product_title_requested = p['title']
                request_type = 'product_detail'
                break

    if request_type == 'product_detail':
        payload['type'] = 'product_detail'
        payload['product_title'] = product_title_requested
    else:
        # Normal message flow
        payload['message'] = user_message
        # If location is provided
        if latitude and longitude:
            payload['location'] = {
                'latitude': float(latitude),
                'longitude': float(longitude)
            }

    # Send request to the backend API
    try:
        resp = requests.post(API_ENDPOINT, json=payload)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"API request failed: {e}")
        return respond("Sorry, I'm having trouble connecting to the server. Please try again later.")

    # Handle the API response
    gpt_response = data.get('reply', '')
    mentioned_products = data.get('mentioned_products', [])

    # Store mentioned products in session for future detail requests
    session_data['last_mentioned_products'] = mentioned_products

    # Construct reply
    # If products are mentioned, guide the user to type the product title to see more details.
    if mentioned_products:
        product_list_text = "\n".join([f"- {p['title']}" for p in mentioned_products])
        gpt_response += f"\n\nWe have these products mentioned above. To get more details on any product, just reply with the product name:\n{product_list_text}"

    return respond(gpt_response)


def respond(message):
    # Twilio expects a TwiML response
    resp = MessagingResponse()
    resp.message(message)
    return make_response(str(resp), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
