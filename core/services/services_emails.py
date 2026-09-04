from django.core.mail import EmailMessage
from django.conf import settings

# from decouple import config
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint


def open_and_return(my_file):
    with open(
        settings.BASE_DIR_OS + "/core/template_emails/" + my_file, "r", encoding="utf-8"
    ) as file:
        data = file.read()
    return data


def send_email_forgot_password(email, name, link):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = settings.SIB_API_KEY

    template = open_and_return("forgot_password.html").format(link)

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )
    subject = "Redefinir senha"
    html_content = template
    sender = {"name": "Noclaf", "email": "no-reply@noclaf.com.br"}
    email = [{"email": email, "name": name}]
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=email, html_content=html_content, sender=sender, subject=subject
    )

    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        pprint(api_response)
    except ApiException as e:
        print("Exception when calling SMTPApi->send_transac_email: %s\n" % e)
