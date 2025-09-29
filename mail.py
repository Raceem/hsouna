import imaplib
import email
from email.header import decode_header
import re
import time
from utils import remove_dots


""""""
def get_verification_code(email1):
    # Paramètres de connexion pour Gmail
    email1=remove_dots(email1)
    
    if email1=="ossjegzbdehkerbufrayzen@gmail.com":
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
    elif email1== "amineayedi21288@gmail.com" :
        EMAIL = "amineayedi21288@gmail.com"
        PASSWORD = "afnz nzsa bkqv lupd"

    print(EMAIL)
    IMAP_SERVER = "imap.gmail.com"
    IMAP_PORT = 993

    # Connexion au serveur IMAP Gmail
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL, PASSWORD)

    # Sélectionner la boîte de réception
    mail.select("inbox")
    time.sleep(2)
    # Chercher tous les messages dans la boîte de réception
    status, messages = mail.search(None, 'ALL')
    if status != "OK":
        print("❌ Aucun message trouvé.")
        return None

    # Récupérer l'ID du dernier message
    latest_email_id = messages[0].split()[-1]

    # Récupérer le dernier email
    status, msg_data = mail.fetch(latest_email_id, "(RFC822)")
    if status != "OK":
        print("❌ Impossible de récupérer l'email.")
        return None

    # Extraire l'e-mail
    for response_part in msg_data:
        if isinstance(response_part, tuple):
            msg = email.message_from_bytes(response_part[1])

            # Décoder l'objet du mail
            subject, encoding = decode_header(msg["Subject"])[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding if encoding else "utf-8")
            print("📧 Objet du mail : ", subject)

            # Vérifier si l'email a plusieurs parties (texte brut et HTML)
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        # Extraire le corps du texte brut
                        body = part.get_payload(decode=True).decode()
                        print("📝 Corps du mail : ", body)
                        break
            else:
                # Si l'email n'a qu'une seule partie (texte brut ou HTML)
                body = msg.get_payload(decode=True).decode()
                print("📝 Corps du mail : ", body)

            # Utiliser une regex pour extraire le code à 4 chiffres
            match = re.search(r"(\d{4})", body)  # Recherche de 4 chiffres consécutifs
            if match:
                return match.group(1)
            else:
                print("❌ Code de vérification non trouvé dans l'e-mail.")
                return None
"""dates = re.findall(r'(\d{2}[-/]\d{2}[-/]\d{4})', text)
            print(dates)
            date_de_naissance = ""
            for date in dates:
                try:
                    day, month, year = map(int, date.split('/'))
                    if 1800 < year < 2025:
                        date_de_naissance = date
                        break
                except:
                    print('no dates')
                    continue"""