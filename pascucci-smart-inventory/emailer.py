import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

def send_email(smtp_host, smtp_port, username, password, to_emails, subject, body, attachments=None, use_tls=True):
    msg = MIMEMultipart()
    msg['From'] = username
    msg['To'] = ', '.join(to_emails)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    for att in (attachments or []):
        p = Path(att)
        if p.exists():
            part = MIMEBase('application','octet-stream')
            with open(p, 'rb') as f:
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{p.name}"')
            msg.attach(part)

    server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
    if use_tls:
        server.starttls()
    server.login(username, password)
    server.sendmail(username, to_emails, msg.as_string())
    server.quit()
