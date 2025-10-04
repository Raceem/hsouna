import datetime
import imaplib
import email
from email.header import decode_header
import re
import time
from utils import remove_dots

def get_verification_code(target_email):

    lookback=5
    # Paramètres de connexion pour Gmail
    email1=remove_dots(target_email)
    
    
    if email1=="sjgefrhgjqsgryagiurdqgghyrbqfu@gmail.com":
        EMAIL = "sjgefrhgjqsgryagiurdqgghyrbqfu@gmail.com"
        PASSWORD = "sqxj lvow egqu rtcf"
    elif email1=="kksjdejdnkdhdhdbdgjsjkhefchy@gmail.com":
        EMAIL = "kksjdejdnkdhdhdbdgjsjkhefchy@gmail.com"
        PASSWORD = "zklc awfm twez uqge"
    elif email1=="ossjegzbdehkerbufrayzen@gmail.com":
        EMAIL = "ossjegzbdeh.kerbufrayzen@gmail.com"
        PASSWORD = "obbo hsoy snlh ovtp"  # Idéalement, utilise un mot de passe spécifique pour les applications si activé
    elif email1== "mailboybanana@gmail.com" :
        EMAIL = "mailboybanana@gmail.com"
        PASSWORD = "szim wisj vgns blrt"
    elif  email1=="oskkskdjskkskskslkhsounsjkeksn@gmail.com":
        EMAIL = "oskkskdjskkskskslkhsounsjkeksn@gmail.com"
        PASSWORD = "kxqg rnzh fzhf dugi"
    elif email1== "hkobbi12@gmail.com" :
        EMAIL = "h.kobbi.12@gmail.com"
        PASSWORD = "ugqm lfig dxxh aguc"
    elif email1== "gethacked045@gmail.com" :
        EMAIL = "gethacked045@gmail.com"
        PASSWORD = "ddhl vkcj nzqe ehkn"
    elif email1== "amineayedi21288@gmail.com" :
        EMAIL = "amineayedi21288@gmail.com"
        PASSWORD = "afnz nzsa bkqv lupd"
    elif email1== "bakloutimhamed01@gmail.com" :
        EMAIL = "bakloutimhamed01@gmail.com"
        PASSWORD = "vnio gnyq jhcg arct"
    print(EMAIL)
    IMAP_SERVER = "imap.gmail.com"
    IMAP_PORT = 993

    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")
    # Fetch only today's emails to reduce search results
    since = datetime.date.today().strftime("%d-%b-%Y")
    status, messages = mail.search(None, f'(SINCE "{since}")')
    if status != "OK" or not messages[0]:
        print("❌ No emails found in inbox")
        return None

    email_ids = messages[0].split()[-lookback:]  # only last N emails

    for eid in reversed(email_ids):
        # Fetch only headers first (faster)
        status, msg_data = mail.fetch(eid, '(BODY.PEEK[HEADER.FIELDS (TO DELIVERED-TO SUBJECT)])')
        if status != "OK":
            continue

        headers = email.message_from_bytes(msg_data[0][1])
        to_email = headers.get("To", "")
        delivered_to = headers.get("Delivered-To", "")
        if target_email not in to_email and target_email not in delivered_to:
            continue

        # Now fetch full email body only if needed
        status, full_msg_data = mail.fetch(eid, "(BODY.PEEK[])")
        if status != "OK":
            continue

        msg = email.message_from_bytes(full_msg_data[0][1])

        body = None
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        if body:
            match = re.search(r"\b(\d{4})\b", body)
            if match:
                print(f"✅ Code found in email for {target_email}: {match.group(1)}")
                return match.group(1)

    # 👉 Fallback: if no matching email found, take the very last email
    print("The code of the last email")
    last_email_id = email_ids[-1]
    status, full_msg_data = mail.fetch(last_email_id, "(BODY.PEEK[])")
    if status == "OK":
        msg = email.message_from_bytes(full_msg_data[0][1])
        body = None
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        if body:
            match = re.search(r"\b(\d{4})\b", body)
            if match:
                print(f"✅ Code found in last email (fallback): {match.group(1)}")
                return match.group(1)

    print(f"❌ No verification code found for {target_email} in last {lookback} emails (and last email fallback)")
    return None