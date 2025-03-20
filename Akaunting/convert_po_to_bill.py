import requests
from utils.logger import log_info
import config
import sys
import os
# Get the parent directory of the current script
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Add parent directory to sys.path
sys.path.append(parent_dir)

# Now import db_access
from db_access import InventoryValidator

# Zoho API credentials from config
ZOHO_ORG_ID = config.ZOHO_ORG_ID
ZOHO_ACCESS_TOKEN = config.ZOHO_ACCESS_TOKEN
ZOHO_REFRESH_TOKEN = config.ZOHO_REFRESH_TOKEN
ZOHO_CLIENT_ID = config.ZOHO_CLIENT_ID
ZOHO_CLIENT_SECRET = config.ZOHO_CLIENT_SECRET

HEADERS = {
    "Authorization": f"Zoho-oauthtoken {ZOHO_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def refresh_access_token():
    """
    Refresh Zoho API Access Token using the Refresh Token.
    """
    log_info("🔄 Access token expired. Refreshing token...")
    
    url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }

    response = requests.post(url, data=data)
    token_data = response.json()

    if "access_token" in token_data:
        new_token = token_data["access_token"]
        log_info("✅ Access token refreshed successfully.")

        # Update global access token
        global ZOHO_ACCESS_TOKEN
        ZOHO_ACCESS_TOKEN = new_token
        global HEADERS
        HEADERS["Authorization"] = f"Zoho-oauthtoken {new_token}"

        # Save new token to config (optional)
        config.ZOHO_ACCESS_TOKEN = new_token
        return new_token
    else:
        log_info(f"❌ Failed to refresh token: {token_data.get('error')}")
        return None

# Function to get authorization headers (refreshing token if needed)
def get_auth_headers():
    """Generate authorization headers with a valid Zoho access token."""
    global ZOHO_ACCESS_TOKEN

    headers = {
        "Authorization": f"Zoho-oauthtoken {ZOHO_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Test if the token is valid
    test_url = f"https://www.zohoapis.in/books/v3/organizations/{ZOHO_ORG_ID}"
    response = requests.get(test_url, headers=headers)
    
    if response.status_code == 401:  # Unauthorized → Token expired
        log_info("🔄 Access token expired. Refreshing token...")
        ZOHO_ACCESS_TOKEN = refresh_access_token()
        if ZOHO_ACCESS_TOKEN:
            headers["Authorization"] = f"Zoho-oauthtoken {ZOHO_ACCESS_TOKEN}"
        else:
            log_info("❌ Could not refresh access token. Exiting.")
            return None
    
    return headers

# Function to convert a PO to a Bill
def convert_po_to_bill(po_short,po_id, email_id):
    """
    Convert a Purchase Order to a Bill using Zoho Books API.
    """
    log_info(f"🟡 Attempting to convert PO {po_id} to Bill...")
    
    # Use the get_auth_headers function to handle token refresh if needed
    headers = get_auth_headers()
    if not headers:
        return None

    # Step 1: Get PO data to convert to bill format
    url = f"https://www.zohoapis.in/books/v3/bills/editpage/frompurchaseorders?purchaseorder_ids={po_id}&organization_id={ZOHO_ORG_ID}"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 401:  # Handle expired token
        headers = get_auth_headers()
        if not headers:
            return None
        response = requests.get(url, headers=headers)  # Retry with new token
    
    po_data = response.json()
    if po_data.get("code") != 0:
        log_info(f"❌ Error fetching PO details: {po_data.get('message')}")
        return None

    bill_data = po_data.get("bill", {})

    # Step 2: Prepare Bill Data - only keep necessary fields
    filtered_bill_data = {
        "purchaseorder_ids": bill_data.get("purchaseorder_ids"),
        "vendor_id": bill_data.get("vendor_id"),
        "bill_number": f"{bill_data.get('reference_number', po_id)}",
        "date": bill_data.get("date"),
        "due_date": bill_data.get("due_date"),
        "currency_id": bill_data.get("currency_id"),
        "line_items": bill_data.get("line_items", []),
        "reference_number": bill_data.get("reference_number"),
        "status": "draft"
    }

    # Step 3: Create Bill in Zoho Books
    create_bill_url = f"https://www.zohoapis.in/books/v3/bills?organization_id={ZOHO_ORG_ID}"
    create_response = requests.post(create_bill_url, headers=headers, json=filtered_bill_data)

    # Handle expired token again (in case it expired mid-request)
    if create_response.status_code == 401:
        headers = get_auth_headers()
        if not headers:
            return None
        create_response = requests.post(create_bill_url, headers=headers, json=filtered_bill_data)

    create_data = create_response.json()

    if create_data.get("code") == 0:
        bill_id = create_data["bill"]["bill_id"]
        validator = InventoryValidator()
        validator.test_connection()
        validator.insert_bill_id(bill_id, email_id)
        log_info(f"✅ Successfully converted PO {po_id} to Bill {bill_id}")
        validator.log_to_system('invoice',po_short,{},'PO converted to bill and set as draft!')
        return bill_id
    else:
        log_info(f"❌ Error creating Bill: {create_data.get('message')}")
        return None