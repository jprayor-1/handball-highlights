import os
import logging
import resend

logger = logging.getLogger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")

FROM_EMAIL = os.environ.get("FROM_EMAIL", "highlights@yourdomain.com")
APP_URL = os.environ.get("APP_URL", "https://yourapp.com")


def send_job_complete_email(email: str, highlight_count: int, job_id: str) -> None:
    if not resend.api_key:
        logger.warning({"event": "email_skipped", "reason": "RESEND_API_KEY not set"})
        return

    results_url = f"{APP_URL}/results/{job_id}"

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": email,
            "subject": "Your handball highlights are ready!",
            "html": f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
                    <h1 style="font-size: 24px; font-weight: 800; text-transform: uppercase; letter-spacing: 2px;">
                        Your Highlights Are Ready
                    </h1>
                    <p style="color: #555; font-size: 16px;">
                        We found <strong>{highlight_count} highlight{'' if highlight_count == 1 else 's'}</strong> from your game footage.
                    </p>
                    <a href="{results_url}" style="display: inline-block; margin-top: 16px; padding: 12px 24px;
                        background: #000; color: #fff; text-decoration: none; font-weight: 700;
                        border-radius: 8px; text-transform: uppercase; letter-spacing: 1px;">
                        View Highlights
                    </a>
                    <p style="margin-top: 32px; color: #999; font-size: 13px;">
                        Handball Highlights &mdash; auto-generated from your game footage
                    </p>
                </div>
            """,
        })
        logger.info({"event": "email_sent", "to": email, "highlights": highlight_count})
    except Exception as e:
        logger.exception({"event": "email_failed", "to": email, "error": str(e)})


def send_job_failed_email(email: str) -> None:
    if not resend.api_key:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": email,
            "subject": "Something went wrong with your highlights",
            "html": f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
                    <h1 style="font-size: 24px; font-weight: 800; text-transform: uppercase; letter-spacing: 2px;">
                        Processing Failed
                    </h1>
                    <p style="color: #555; font-size: 16px;">
                        We ran into an issue processing your handball footage. Please try uploading again.
                    </p>
                    <a href="{APP_URL}" style="display: inline-block; margin-top: 16px; padding: 12px 24px;
                        background: #000; color: #fff; text-decoration: none; font-weight: 700;
                        border-radius: 8px; text-transform: uppercase; letter-spacing: 1px;">
                        Try Again
                    </a>
                    <p style="margin-top: 32px; color: #999; font-size: 13px;">
                        Handball Highlights &mdash; auto-generated from your game footage
                    </p>
                </div>
            """,
        })
        logger.info({"event": "failure_email_sent", "to": email})
    except Exception as e:
        logger.exception({"event": "failure_email_failed", "to": email, "error": str(e)})
