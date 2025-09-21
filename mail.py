import imaplib
import email
from email.header import decode_header
import re
from utils import remove_dots


def get_verification_code(target_email):

    lookback=5
    # Paramètres de connexion pour Gmail
    email1=remove_dots(target_email)
    
    if email1=="kksjdejdnkdhdhdbdgjsjkhefchy@gmail.com":
        EMAIL = "kksjdejdnkdhdhdbdgjsjkhefchy@gmail.com"
        PASSWORD = "zklc awfm twez uqge"
    elif email1=="ossjegzbdehkerbufrayzen@gmail.com":
        EMAIL = "ossjegzbdeh.kerbufrayzen@gmail.com"
        PASSWORD = "obbo hsoy snlh ovtp"  # Idéalement, utilise un mot de passe spécifique pour les applications si activé
    elif email1== "mailboybanana@gmail.com" :
        EMAIL = "mailboybanana@gmail.com"
        PASSWORD = "szim wisj vgns blrt"
    elif email1=="sjgefrhgjqsgryagiurdqgghyrbqfu@gmail.com":
        EMAIL = "sjgefrhgjqsgryagiurdqgghyrbqfu@gmail.com"
        PASSWORD = "sqxj lvow egqu rtcf"
    elif  email1=="oskkskdjskkskskslkhsounsjkeksn@gmail.com":
        EMAIL = "oskkskdjskkskskslkhsounsjkeksn@gmail.com"
        PASSWORD = "kxqg rnzh fzhf dugi"
    elif email1== "hkobbi12@gmail.com" :
        EMAIL = "h.kobbi.12@gmail.com"
        PASSWORD = "ugqm lfig dxxh aguc"
    elif email1== "gethacked045@gmail.com" :
        EMAIL = "gethacked045@gmail.com"
        PASSWORD = "ddhl vkcj nzqe ehkn"
    elif email1== "bakloutimhamed01@gmail.com" :
        EMAIL = "bakloutimhamed01@gmail.com"
        PASSWORD = "vnio gnyq jhcg arct"
    print(EMAIL)
    IMAP_SERVER = "imap.gmail.com"
    IMAP_PORT = 993

    # Connexion au serveur IMAP Gmail
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL, PASSWORD)

    # Sélectionner la boîte de réception
    mail.select("inbox")

    # Chercher tous les messages dans la boîte de réception
    status, messages = mail.search(None, "ALL")
    if status != "OK" or not messages[0]:
        print("❌ No emails found in inbox")
        return None

    email_ids = messages[0].split()
    # Take only the last `lookback` emails
    recent_ids = email_ids[-lookback:]

    for eid in reversed(recent_ids):  # check newest first
        status, msg_data = mail.fetch(eid, "(RFC822)")
        if status != "OK":
            continue

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])

                # check recipient
                to_email = msg.get("To", "")
                delivered_to = msg.get("Delivered-To", "")
                if target_email not in to_email and target_email not in delivered_to:
                    continue  # skip if not for our target

                # decode subject
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else "utf-8")

                # get body
                body = None
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")

                # find 4-digit code
                if body:
                    match = re.search(r"\b(\d{4})\b", body)
                    if match:
                        print(f"✅ Code found in email for {target_email}: {match.group(1)}")
                        return match.group(1)

    print(f"❌ No verification code found for {target_email} in last {lookback} emails")
    return None