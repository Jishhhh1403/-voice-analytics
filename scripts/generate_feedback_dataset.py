#!/usr/bin/env python3
"""Generate a large, taxonomy-covered synthetic banking feedback dataset.

The generator reads ``taxonomy/banking_taxonomy_v1.yaml`` and guarantees that
every active feature node receives feedback. Remaining rows are distributed by
module weight so the dataset still resembles real feedback volume (payments and
authentication dominate). The output is deterministic for a given seed.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY = REPO_ROOT / "taxonomy" / "banking_taxonomy_v1.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "synthetic_banking_app_feedback_15000.csv"
COLUMNS = [
    "feedback_id",
    "submitted_at",
    "source_type",
    "source_channel",
    "platform",
    "app_version",
    "language",
    "synthetic_customer_ref",
    "rating_1_to_5",
    "feedback_title",
    "feedback_text",
    "is_synthetic",
]

START_DATE = datetime(2025, 12, 1, tzinfo=UTC)
END_DATE = datetime(2026, 11, 30, tzinfo=UTC)
APP_VERSIONS = ["5.0.2", "5.1.0", "5.1.3", "5.2.0", "5.2.1", "5.3.0", "5.3.2", "5.4.0", "5.4.1"]

MODULE_WEIGHTS = {
    "payments": 0.20,
    "authentication": 0.12,
    "cards": 0.11,
    "accounts": 0.10,
    "beneficiaries": 0.09,
    "support": 0.09,
    "onboarding": 0.08,
    "statements": 0.08,
    "loans": 0.06,
    "deposits": 0.05,
    "notifications": 0.02,
    "navigation": 0.01,
}

FEATURE_WEIGHT_OVERRIDES = {
    "payments.status": 1.7,
    "payments.upi": 1.5,
    "payments.bill_payment": 1.3,
    "payments.imps": 1.2,
    "auth.login": 1.5,
    "auth.otp": 1.4,
    "cards.controls": 1.2,
    "cards.usage": 1.2,
    "beneficiary.add": 1.3,
    "support.chat": 1.3,
    "navigation.performance": 1.5,
    "navigation.stability": 1.4,
    "statements.download": 1.2,
    "accounts.history": 1.2,
    "loans.emi": 1.2,
}

SOURCE_PROFILES = [
    {"source_type": "app_store_review", "source_channel": "google_play", "platform": "Android", "weight": 0.29, "version_prob": 0.9, "rating_missing": 0.01},
    {"source_type": "app_store_review", "source_channel": "apple_app_store", "platform": "iOS", "weight": 0.14, "version_prob": 0.9, "rating_missing": 0.01},
    {"source_type": "in_app_feedback", "source_channel": "in_app", "platform": "Android", "weight": 0.11, "version_prob": 0.75, "rating_missing": 0.2},
    {"source_type": "in_app_feedback", "source_channel": "in_app", "platform": "iOS", "weight": 0.08, "version_prob": 0.75, "rating_missing": 0.2},
    {"source_type": "in_app_feedback", "source_channel": "in_app", "platform": "Web", "weight": 0.04, "version_prob": 0.0, "rating_missing": 0.25},
    {"source_type": "post_interaction_survey", "source_channel": "survey", "platform": "Android", "weight": 0.07, "version_prob": 0.5, "rating_missing": 0.1},
    {"source_type": "post_interaction_survey", "source_channel": "survey", "platform": "iOS", "weight": 0.05, "version_prob": 0.5, "rating_missing": 0.1},
    {"source_type": "post_interaction_survey", "source_channel": "survey", "platform": "Unknown", "weight": 0.03, "version_prob": 0.0, "rating_missing": 0.15},
    {"source_type": "complaint_portal", "source_channel": "complaint_portal", "platform": "Web", "weight": 0.07, "version_prob": 0.0, "rating_missing": 0.6},
    {"source_type": "complaint_portal", "source_channel": "complaint_portal", "platform": "Unknown", "weight": 0.02, "version_prob": 0.0, "rating_missing": 0.7},
    {"source_type": "support_chat_summary", "source_channel": "support_chat", "platform": "Unknown", "weight": 0.06, "version_prob": 0.2, "rating_missing": 0.85},
    {"source_type": "support_chat_summary", "source_channel": "support_chat", "platform": "Web", "weight": 0.04, "version_prob": 0.0, "rating_missing": 0.9},
]

PREAMBLES = [
    "I have been using this app for over a year.",
    "Over the past week this has happened several times.",
    "This is really frustrating.",
    "Sharing my experience with the app.",
    "I want to flag a serious issue.",
    "Just to report a problem I faced today.",
    "I have already tried restarting the app.",
    "This started after the latest update.",
]

CLOSINGS = [
    "Please fix this soon.",
    "This has happened more than once.",
    "Kindly look into it.",
    "Please resolve this at the earliest.",
    "I expect a proper response.",
    "This needs urgent attention.",
    "I hope this is fixed in the next update.",
    "Please confirm once it is resolved.",
]

HINGLISH_TAILS = [
    "Ye feature theek se kaam nahi kar raha hai, please jaldi fix karo.",
    "Mera paisa kat gaya hai par confirm nahi hua, please check karo.",
    "App bahut slow ho gaya hai aur kaam nahi kar raha, jaldi solve karo.",
    "Mujhe baar baar error aa raha hai, please isko theek karo.",
    "Support se baat nahi ho rahi hai, koi update nahi mil raha.",
    "Ye problem roz aa rahi hai aur main pareshan hoon, please help karo.",
]

PII_TAILS = [
    "You can contact me on 9876543210 or at anita.sharma@example.com.",
    "Please call me on 9123456780 or email rahul.verme@example.com.",
    "My number is 9988776655 and my email is priya.nair@example.com.",
]

DETAILS = [
    "This has happened more than once.",
    "I have tried this on two different days.",
    "I have screenshots of the problem.",
    "It happens every time I open this screen.",
    "This is affecting my daily banking.",
    "I am using the latest version of the app.",
    "I have already restarted the app.",
    "I am reporting this from {city}.",
    "This started a few days ago.",
    "I have been waiting for a resolution.",
    "The issue is still there today.",
    "I have not changed any settings.",
    "It worked earlier but now it fails.",
    "I tried again just now and got the same result.",
    "I have also checked on another device.",
    "This keeps happening during peak hours.",
]

MERCHANTS = ["QuickMart", "FreshKart", "Metro Cafe", "SkyTel", "City Pharmacy", "Fashion Hub"]
BILLERS = ["Metro Power", "City Water Board", "SkyTel Postpaid", "Green Gas", "DTH Prime"]
CITIES = ["Pune", "Jaipur", "Kochi", "Indore", "Lucknow", "Nagpur", "Surat", "Bhopal"]
BENEFICIARIES = ["Rakesh Kumar", "Sunita Devi", "Arjun Mehta", "Neha Iyer", "Vikram Singh", "Farah Khan"]

PROBLEMS: dict[str, list[str]] = {
    "auth.login": [
        "I cannot log in to the app even though my username and password are correct.",
        "The login screen keeps rejecting my password and shows a generic error.",
        "I am unable to sign in to my account after updating the app.",
        "Every time I enter my password, the login button does nothing.",
        "The app sends me back to the login page as soon as I sign in.",
    ],
    "auth.password_reset": [
        "I forgot my password and the reset password link never arrives.",
        "The change password option keeps failing with an error.",
        "Password reset does not work because the reset OTP is never delivered.",
        "After resetting my password, the app still rejects the new credentials.",
        "There is no clear way to recover my account when I forget my password.",
    ],
    "auth.otp": [
        "The OTP for login arrives very late, so I cannot complete the verification.",
        "The app keeps saying invalid OTP even when I enter the correct one-time password.",
        "I receive duplicate OTP messages and then the verification code times out.",
        "The OTP screen freezes and I have to request a new security code again.",
        "No SMS with the security code reaches my phone, so login is blocked.",
    ],
    "auth.biometric": [
        "Fingerprint login stopped working after the latest update.",
        "Face ID is not recognised and the app falls back to the password every time.",
        "Biometric login is enabled but the app still asks for my password.",
        "Face recognition fails in low light and there is no clear retry option.",
        "The fingerprint prompt closes immediately and I cannot sign in.",
    ],
    "auth.session": [
        "The app logs me out after a few minutes and I have to sign in again.",
        "My session expires too quickly even when I am actively using the app.",
        "I am signed out in the middle of a payment without any warning.",
        "Re-authentication keeps looping and I cannot get back to my account.",
        "The session timeout is too short and interrupts every task.",
    ],
    "payments.upi": [
        "My UPI payment to a merchant failed but the money was debited.",
        "The app does not recognise the merchant QR code and shows an error.",
        "A UPI transfer to a VPA is stuck as pending for several hours.",
        "UPI payments are declined repeatedly even though my balance is sufficient.",
        "The merchant payment through UPI does not show a confirmation.",
    ],
    "payments.imps": [
        "My IMPS transfer is still pending and I cannot see what to do next.",
        "The IMPS payment failed but the amount was debited from my account.",
        "IMPS transfers take too long and the status does not change.",
        "The app shows an IMPS failure without a transaction reference.",
        "I cannot complete an immediate transfer because IMPS keeps timing out.",
    ],
    "payments.neft": [
        "My NEFT transfer is stuck in pending even after the cut-off time.",
        "The NEFT payment was rejected without explaining the reason.",
        "NEFT status does not update and I cannot find the transaction reference.",
        "I scheduled an NEFT transfer but it was not processed on the chosen date.",
        "The app shows NEFT as successful even though the beneficiary did not receive the money.",
    ],
    "payments.rtgs": [
        "My high value RTGS transfer is pending for more than a day.",
        "RTGS payment failed but the amount is still on hold.",
        "The app does not show the RTGS reference number or the next step.",
        "RTGS transfers above the limit are rejected with a confusing error.",
        "I cannot complete a real time gross settlement transfer from the app.",
    ],
    "payments.status": [
        "The transfer status stays pending and the app does not explain what to do next.",
        "I am not sure whether my transfer was submitted because there is no confirmation.",
        "The transaction reference is missing from the confirmation screen.",
        "After a failed transfer, the app does not tell me whether to retry.",
        "The status changed to successful but the beneficiary has not received the money.",
    ],
    "payments.bill_payment": [
        "My electricity bill payment failed but the amount was debited.",
        "The biller is not available in the app, so I cannot pay my utility bill.",
        "The credit card bill payment shows pending for two days.",
        "The app does not show a confirmation after paying the bill.",
        "I paid the same bill twice because the first payment showed an error.",
    ],
    "payments.recharge": [
        "My mobile recharge failed but the money was deducted.",
        "The prepaid recharge is stuck and the DTH recharge shows an error.",
        "The app does not confirm whether my recharge was successful.",
        "Recharge plans do not load and the screen keeps showing a spinner.",
        "I recharged the wrong number because the confirmation was unclear.",
    ],
    "payments.refund": [
        "The refund for my failed payment is not visible even after a week.",
        "I cannot track the refund or reversal of my failed UPI transaction.",
        "The app says the money will be refunded but there is no update.",
        "My refund is still pending and customer support has not responded.",
        "The reversal amount does not match the original failed payment.",
    ],
    "beneficiary.add": [
        "I tried to add a new beneficiary but the app keeps rejecting the account details.",
        "Adding a payee fails with an unclear error even when the IFSC is correct.",
        "The new beneficiary form does not save and returns to the first step.",
        "The app does not accept a valid IFSC code while registering a beneficiary.",
        "I cannot add a beneficiary because the account details are shown as invalid.",
    ],
    "beneficiary.verify": [
        "The beneficiary verification is pending and the cooling-off period is not explained.",
        "I did not receive the OTP to verify the new beneficiary.",
        "The app says beneficiary verification failed but does not say why.",
        "Verification has been pending for two days and there is no update.",
        "The cooling-off period blocks my transfer and the app does not show when it ends.",
    ],
    "beneficiary.edit": [
        "I cannot edit the beneficiary details because the update button does not work.",
        "Editing a payee reverts to the old details after saving.",
        "The app does not let me change the beneficiary account number.",
        "Updating a saved beneficiary fails without any error message.",
        "After editing a beneficiary, the changes are not reflected in the transfer screen.",
    ],
    "beneficiary.delete": [
        "I cannot delete an old beneficiary from the saved list.",
        "The remove payee option is missing or does not respond.",
        "Deleting a beneficiary shows an error and the payee remains saved.",
        "The app does not confirm when a beneficiary is deleted.",
        "I removed a beneficiary but it still appears during transfer.",
    ],
    "beneficiary.select": [
        "The saved beneficiaries do not appear when I try to select a payee.",
        "The app does not list my saved beneficiary during transfer.",
        "Selecting a beneficiary resets the form and I have to start again.",
        "The choose payee screen is slow and sometimes shows an empty list.",
        "I cannot find the beneficiary I added earlier while making a transfer.",
    ],
    "accounts.overview": [
        "The account overview does not show my recent transactions.",
        "My dashboard is blank after login and the account summary does not load.",
        "The account overview shows an old balance that does not match my account.",
        "Recent transactions on the dashboard are missing or duplicated.",
        "The home overview takes too long to load my accounts.",
    ],
    "accounts.balance": [
        "The available balance does not refresh and shows an old amount.",
        "My account balance is different from what the bank statement shows.",
        "The balance screen keeps loading and never displays the amount.",
        "I cannot check the available balance from the app.",
        "The balance shown is incorrect after a recent transaction.",
    ],
    "accounts.history": [
        "The transaction history does not show my recent transactions.",
        "Transaction descriptions are incomplete and I cannot recognise the merchant.",
        "Searching the transaction list returns no results even for recent payments.",
        "The transaction history is missing entries from the last two days.",
        "The app shows duplicate transactions in my account history.",
    ],
    "accounts.details": [
        "My account details show the wrong account number.",
        "The IFSC code in the account information is incorrect.",
        "The app does not show my account number or branch details.",
        "Account details are outdated and there is no way to update them.",
        "The account information screen loads an error instead of my details.",
    ],
    "statements.range": [
        "I cannot select the previous financial year as the statement date range.",
        "The custom range option resets when I change the statement period.",
        "The app does not allow a statement period longer than three months.",
        "The date range picker is confusing and rejects valid dates.",
        "The statement range always defaults to the current month.",
    ],
    "statements.generate": [
        "The account statement fails to generate and the screen shows an error.",
        "Statement generation is stuck at zero percent for a long time.",
        "The app cannot generate a statement for the selected period.",
        "Generating the PDF statement keeps failing with a technical error.",
        "The statement is generated but it is blank and incomplete.",
    ],
    "statements.download": [
        "I cannot download my account statement as a PDF.",
        "The statement download gives a blank PDF every time.",
        "The download button does not respond and the spinner keeps loading.",
        "Downloading the bank statement fails at the last step.",
        "The app saves an empty file instead of the PDF statement.",
    ],
    "statements.share": [
        "I cannot share or email my account statement from the app.",
        "The share statement option fails and the email never arrives.",
        "Sending the statement by email shows an error.",
        "The shared statement link does not open.",
        "There is no clear option to send the statement to another person.",
    ],
    "cards.controls": [
        "The card controls toggle does not save after I change it.",
        "I cannot turn online usage on or off from card settings.",
        "The card settings revert to the previous state after saving.",
        "The app does not let me manage my debit card controls.",
        "The international usage toggle switches off by itself.",
    ],
    "cards.limits": [
        "I cannot change my ATM withdrawal limit from the app.",
        "The card limit update fails with an unclear error.",
        "My transaction limit is lower than the amount I set.",
        "The payment limit screen does not save the new value.",
        "The app shows a different card limit from the one I requested.",
    ],
    "cards.block": [
        "I cannot block my lost debit card from the app.",
        "The unblock card option is not working and shows an error.",
        "I reported my card lost but it is still active.",
        "Blocking the card does not show a confirmation.",
        "The freeze card option is missing from card settings.",
    ],
    "cards.replacement": [
        "I requested a replacement card but there is no tracking update.",
        "The card replacement request keeps failing.",
        "The app does not show the delivery status of my replacement card.",
        "I cannot order a replacement debit card from the app.",
        "The replacement card was delivered to the wrong address and the app does not let me change it.",
    ],
    "cards.online": [
        "My online card payment is declined even though online usage is enabled.",
        "The app does not allow me to enable online usage for my card.",
        "Online payments fail on e-commerce sites after the latest update.",
        "The card is not accepted for online transactions but there is no explanation.",
        "The online usage setting does not stay enabled.",
    ],
    "cards.international": [
        "International usage on my card is blocked without any notice.",
        "My overseas card transaction was declined even after enabling international usage.",
        "The app does not explain the foreign transaction charges.",
        "I cannot switch on international usage while travelling.",
        "The international toggle does not save and the card fails abroad.",
    ],
    "cards.usage": [
        "My card payment was declined at the merchant even though I have sufficient balance.",
        "Card transactions are failing repeatedly and the app shows no reason.",
        "The app does not show the merchant name for some card payments.",
        "A card transaction was successful but the amount shown is wrong.",
        "I see duplicate card transactions for a single purchase.",
    ],
    "deposits.booking": [
        "I cannot book a fixed deposit from the app.",
        "The deposit booking fails at the payment step.",
        "The interest rate shown changes on the confirmation screen.",
        "The app does not let me choose the tenure for a fixed deposit.",
        "Booking an FD returns an error even though the amount is within limits.",
    ],
    "deposits.maturity": [
        "The maturity date shown for my deposit is wrong.",
        "I cannot see the maturity value or interest paid on my fixed deposit.",
        "The app does not show any details for my term deposit.",
        "The deposit maturity amount is different from the one promised at booking.",
        "The maturity reminder arrived after the deposit had already renewed.",
    ],
    "deposits.renewal": [
        "I cannot renew my fixed deposit from the app.",
        "The auto renewal option does not work and the deposit is still pending.",
        "The app renewed my deposit without asking me.",
        "The renewal interest rate is not shown before confirmation.",
        "I tried to renew my term deposit but the request failed.",
    ],
    "deposits.premature_closure": [
        "The premature closure penalty is not explained before I close the deposit.",
        "I cannot close my fixed deposit early from the app.",
        "The early closure request is stuck and the deposit is still active.",
        "The app shows the wrong penalty for premature closure.",
        "Closing my deposit early failed without any confirmation.",
    ],
    "deposits.advice": [
        "I did not receive the deposit advice for my new fixed deposit.",
        "The deposit certificate is not available in the app.",
        "The deposit statement does not download.",
        "The deposit advice shows the wrong amount.",
        "I cannot find the deposit advice for my term deposit.",
    ],
    "loans.eligibility": [
        "The app says I am not eligible for a loan even though I meet the criteria.",
        "The pre-approved loan offer is not visible in the app.",
        "The loan eligibility check keeps loading and never completes.",
        "The eligible loan amount shown is much lower than expected without explanation.",
        "I cannot check my loan eligibility from the app.",
    ],
    "loans.application": [
        "The loan application form resets and I have to start again.",
        "Applying for a loan fails at the document step.",
        "The app does not let me complete the loan application.",
        "The loan form rejects valid details with an unclear error.",
        "The application is submitted but I receive no confirmation.",
    ],
    "loans.documents": [
        "The salary slip upload for my loan is stuck at zero percent.",
        "The app rejects a valid loan document without saying why.",
        "I cannot upload the required documents for my loan application.",
        "The loan document upload fails repeatedly and restarts the form.",
        "The loan document status does not update after upload.",
    ],
    "loans.status": [
        "My loan application status has not changed for a week.",
        "The app does not show whether my loan is approved.",
        "Loan tracking shows no update and there is no reference number.",
        "The loan status screen is stuck on processing.",
        "I cannot find the status of my home loan application.",
    ],
    "loans.emi": [
        "The EMI amount shown in the app is different from my repayment schedule.",
        "I cannot view my EMI schedule or repayment details.",
        "The EMI payment failed and the app does not explain the next step.",
        "The app shows an incorrect instalment amount for my loan.",
        "Repayment details are missing from the loan summary.",
    ],
    "onboarding.kyc": [
        "My KYC verification has been pending for several days.",
        "The app does not say how long KYC verification will take.",
        "KYC failed even though I submitted valid identity documents.",
        "I cannot complete my KYC from the app.",
        "The verification status does not update after submitting the details.",
    ],
    "onboarding.documents": [
        "The document upload for my address proof is stuck.",
        "The app rejects a valid ID proof during onboarding.",
        "I cannot upload my identity document to complete verification.",
        "Document verification failed without any explanation.",
        "The uploaded document disappears and I have to start onboarding again.",
    ],
    "onboarding.selfie": [
        "The selfie verification fails every time I take the photo.",
        "The app does not accept my selfie for identity verification.",
        "The face verification screen is not clear and the capture button does not work.",
        "Selfie verification is stuck and there is no retry option.",
        "The app asks for my selfie again and again during onboarding.",
    ],
    "onboarding.video_kyc": [
        "The video KYC call keeps disconnecting before verification completes.",
        "I cannot start the video KYC from the app.",
        "The video call agent could not verify my identity and there is no next step.",
        "Video KYC is pending and the app does not show a new appointment.",
        "The video verification screen freezes during the call.",
    ],
    "onboarding.address": [
        "My address verification is stuck and there is no update.",
        "The app does not accept my address proof.",
        "I cannot update my address during onboarding.",
        "Address verification failed without a clear reason.",
        "The app shows my old address even after I submitted a new proof.",
    ],
    "support.complaint": [
        "I cannot raise a complaint from the app.",
        "The complaint form fails and the issue is not registered.",
        "The app does not confirm that my complaint was created.",
        "I tried to report an issue but the app closed the form.",
        "There is no clear option to dispute a transaction in the app.",
    ],
    "support.tracking": [
        "My complaint status has not changed and I have received no update.",
        "I cannot track my complaint because the reference number is missing.",
        "The app shows no update on my complaint response.",
        "Tracking my complaint always returns an error.",
        "I raised a complaint but there is no way to check its status.",
    ],
    "support.chat": [
        "The chat support does not connect me to an agent.",
        "The chatbot keeps repeating the same answer and cannot help.",
        "Customer support chat disconnects in the middle of the conversation.",
        "I could not contact support from the app because the chat button does not work.",
        "The support agent chat is very slow and no one responds.",
    ],
    "support.call": [
        "The call support number does not connect and the helpline keeps ringing.",
        "The call back from customer support never arrived.",
        "Phone support put me on hold for a very long time.",
        "I could not reach the helpline from the app.",
        "The call support agent could not resolve my issue.",
    ],
    "support.dispute": [
        "I cannot dispute a transaction from the app.",
        "My transaction dispute is still pending with no update.",
        "The dispute form does not accept the transaction details.",
        "The app rejected my disputed charge complaint.",
        "I raised a dispute but the amount is still deducted.",
    ],
    "notifications.push": [
        "Push notifications do not arrive on my phone.",
        "I receive push alerts for old transactions.",
        "The app sends duplicate push notifications for the same payment.",
        "Push alerts stop working after I update the app.",
        "I cannot turn push notifications on or off.",
    ],
    "notifications.sms": [
        "SMS alerts for transactions arrive very late.",
        "I do not receive SMS alerts when money is debited.",
        "The SMS alert shows the wrong amount.",
        "I get duplicate SMS messages for a single transaction.",
        "Transaction alerts by SMS stopped after I changed my number.",
    ],
    "notifications.email": [
        "Email alerts for my account are not delivered.",
        "The email statement never arrives.",
        "I receive email notifications for someone else's transactions.",
        "Email alert settings do not save.",
        "The email notification shows incomplete transaction details.",
    ],
    "notifications.preferences": [
        "The notification preferences do not save after I change them.",
        "I cannot mute alerts for low value transactions.",
        "The alert settings reset every time I open the app.",
        "There is no option to choose which notifications I receive.",
        "Changing notification settings does not stop unwanted alerts.",
    ],
    "navigation.search": [
        "The search option cannot find features inside the app.",
        "I cannot locate the transfer option in the menu.",
        "The app search returns no results for common actions.",
        "Finding a feature in the app is confusing because labels are unclear.",
        "The search screen keeps loading and does not show anything.",
    ],
    "navigation.home": [
        "The home screen layout changed and I cannot find the main actions.",
        "The back button closes the app instead of going to the previous screen.",
        "The dashboard labels are confusing after the update.",
        "My home screen is blank and does not load the account summary.",
        "The app menu is hard to navigate and important options are hidden.",
    ],
    "navigation.stability": [
        "The app crashes whenever I open the transfer screen.",
        "The app freezes and becomes unresponsive during login.",
        "The app closes suddenly in the middle of a payment.",
        "The app shuts down when I try to upload a document.",
        "The screen freezes and I have to restart the app.",
    ],
    "navigation.performance": [
        "The app is very slow and screens take too long to load.",
        "The payment screen keeps loading and never completes.",
        "The app shows a blank screen and then takes forever to respond.",
        "Everything in the app is sluggish after the latest update.",
        "The transfer flow takes too many taps and is very slow.",
    ],
    "navigation.labels": [
        "The labels in the transfer screen are unclear and confusing.",
        "The wording on the confirmation page does not explain what happened.",
        "Menu labels are misleading and I cannot understand the flow.",
        "The app uses unclear terms that make the process confusing.",
        "The error message is not clear about what I should do next.",
    ],
}

POSITIVE_TEMPLATES = [
    "The {label} flow is easy to use and works well.",
    "I am happy with the {label} experience in the app.",
    "The {label} section is clear and convenient.",
    "{Label} works smoothly and saves me time.",
    "I had a good experience with {label} today.",
]

REQUEST_TEMPLATES = [
    "It would be useful if the {label} screen had more guidance.",
    "Please make the {label} option easier to find in the app.",
    "Kindly add a clearer confirmation on the {label} page.",
    "The {label} feature could be simplified with fewer steps.",
    "It would help to show the status history on the {label} screen.",
]

POSITIVE_DETAILS = [
    "I use it almost every day.",
    "The experience has improved recently.",
    "It is much better than before.",
    "I would recommend it to others.",
    "Keep up the good work.",
    "This is how it should work.",
    "It has never let me down.",
    "The flow is faster than it used to be.",
]

REQUEST_DETAILS = [
    "This would help new users.",
    "I hope this can be added in the next update.",
    "It would reduce confusion.",
    "Many customers would benefit from this.",
    "Please consider this for the next release.",
    "This would make the app more accessible.",
    "It would save time for frequent users.",
    "A short explanation on that screen would help.",
]


def weighted_choice(rng: random.Random, items: list[Any], key: str = "weight") -> Any:
    total = sum(item[key] for item in items)
    marker = rng.random() * total
    upto = 0.0
    for item in items:
        upto += item[key]
        if upto >= marker:
            return item
    return items[-1]


def allocate_counts(
    feature_nodes: list[dict[str, Any]],
    module_of: dict[str, str],
    module_weights: dict[str, float],
    total: int,
    minimum: int,
) -> dict[str, int]:
    if minimum * len(feature_nodes) > total:
        raise ValueError("minimum per node is too high for the requested row count")

    counts = {node["node_id"]: minimum for node in feature_nodes}
    remaining = total - minimum * len(feature_nodes)

    per_module = Counter()
    for node in feature_nodes:
        per_module[module_of[node["node_id"]]] += 1

    weights: dict[str, float] = {}
    for node in feature_nodes:
        node_id = node["node_id"]
        module = module_of[node_id]
        module_weight = module_weights.get(module, 0.01)
        base = module_weight / max(1, per_module[module])
        weights[node_id] = base * FEATURE_WEIGHT_OVERRIDES.get(node_id, 1.0)

    weight_sum = sum(weights.values())
    raw = {node_id: remaining * weights[node_id] / weight_sum for node_id in weights}
    floor_alloc = {node_id: int(value) for node_id, value in raw.items()}
    leftover = remaining - sum(floor_alloc.values())
    ranked = sorted(weights, key=lambda node_id: raw[node_id] - floor_alloc[node_id], reverse=True)
    for node_id in ranked[:leftover]:
        floor_alloc[node_id] += 1
    for node_id, value in floor_alloc.items():
        counts[node_id] += value
    return counts


def load_feature_nodes(path: Path) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    nodes = data.get("nodes") or []
    active = [node for node in nodes if node.get("status", "active") == "active"]
    by_id = {node["node_id"]: node for node in active}

    def module_of(node_id: str) -> str:
        current = by_id.get(node_id)
        seen: set[str] = set()
        while current and current["node_id"] not in seen:
            seen.add(current["node_id"])
            if current.get("node_type") == "module":
                return current["node_id"]
            current = by_id.get(current.get("parent_id") or "")
        return "other"

    feature_nodes = [node for node in active if node.get("node_type") == "feature"]
    modules = {node["node_id"]: module_of(node["node_id"]) for node in feature_nodes}
    version = str(data.get("version", "0.0.0"))
    return feature_nodes, modules, version


def build_context(rng: random.Random) -> dict[str, str]:
    amount = rng.choice(["250", "500", "750", "1200", "2500", "5000", "10000", "25000"])
    return {
        "amount": f"Rs {amount}",
        "amount2": f"Rs {rng.choice(['500', '1500', '3000', '8000'])}",
        "merchant": rng.choice(MERCHANTS),
        "biller": rng.choice(BILLERS),
        "city": rng.choice(CITIES),
        "ref": "TXN" + "".join(str(rng.randint(0, 9)) for _ in range(8)),
        "tenure": rng.choice(["6 months", "1 year", "2 years", "3 years"]),
        "rate": rng.choice(["6.5%", "6.8%", "7.1%", "7.4%"]),
        "limit": "Rs " + rng.choice(["10000", "25000", "50000", "100000"]),
        "emi": "Rs " + rng.choice(["5200", "8400", "12400", "18500"]),
        "loan_amount": "Rs " + rng.choice(["200000", "500000", "1000000"]),
        "deposit_amount": "Rs " + rng.choice(["50000", "100000", "250000"]),
        "beneficiary": rng.choice(BENEFICIARIES),
        "card": rng.choice(["debit card", "credit card"]),
    }


def fill(text: str, context: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda match: context.get(match.group(1), match.group(0)), text)


def generic_positive(rng: random.Random, node: dict[str, Any]) -> str:
    label = node["display_name"]
    template = rng.choice(POSITIVE_TEMPLATES)
    return template.format(label=label.lower(), Label=label)


def generic_request(rng: random.Random, node: dict[str, Any]) -> str:
    label = node["display_name"]
    template = rng.choice(REQUEST_TEMPLATES)
    return template.format(label=label.lower())


def compose_text(
    rng: random.Random,
    node: dict[str, Any],
    feature_nodes: list[dict[str, Any]],
    context: dict[str, str],
) -> tuple[str, str, str]:
    roll = rng.random()
    if roll < 0.62:
        sentiment = "negative"
    elif roll < 0.76:
        sentiment = "mixed"
    elif roll < 0.90:
        sentiment = "positive"
    else:
        sentiment = "request"

    sentences: list[str] = []
    if sentiment in {"negative", "mixed"} and rng.random() < 0.5:
        sentences.append(rng.choice(PREAMBLES))

    if sentiment == "negative":
        sentences.append(fill(rng.choice(PROBLEMS[node["node_id"]]), context))
        if rng.random() < 0.15:
            sentences.append(fill(rng.choice(PROBLEMS[node["node_id"]]), context))
        if rng.random() < 0.12:
            other = rng.choice(feature_nodes)
            if other["node_id"] != node["node_id"]:
                sentences.append(fill(rng.choice(PROBLEMS[other["node_id"]]), context))
    elif sentiment == "mixed":
        sentences.append(fill(rng.choice(PROBLEMS[node["node_id"]]), context))
        sentences.append(generic_positive(rng, node))
        if rng.random() < 0.12:
            other = rng.choice(feature_nodes)
            if other["node_id"] != node["node_id"]:
                sentences.append(fill(rng.choice(PROBLEMS[other["node_id"]]), context))
    elif sentiment == "positive":
        sentences.append(generic_positive(rng, node))
        if rng.random() < 0.35:
            sentences.append(generic_positive(rng, node))
        sentences.append(rng.choice(POSITIVE_DETAILS))
    else:
        sentences.append(generic_request(rng, node))
        if rng.random() < 0.25:
            sentences.append(generic_positive(rng, node))
        sentences.append(rng.choice(REQUEST_DETAILS))

    if sentiment in {"negative", "mixed"}:
        sentences.append(fill(rng.choice(DETAILS), context))

    language = "en"
    if rng.random() < 0.07:
        sentences.append(rng.choice(HINGLISH_TAILS))
        language = "hinglish"
    if rng.random() < 0.015:
        sentences.append(rng.choice(PII_TAILS))

    if sentiment in {"negative", "mixed"} and rng.random() < 0.5:
        sentences.append(rng.choice(CLOSINGS))

    text = " ".join(sentence.strip() for sentence in sentences if sentence.strip())
    return re.sub(r"\s+", " ", text).strip(), language, sentiment


def pick_rating(rng: random.Random, sentiment: str, profile: dict[str, Any]) -> str:
    if rng.random() < profile["rating_missing"]:
        return ""
    if sentiment == "positive":
        return rng.choices(["4", "5"], weights=[0.55, 0.45])[0]
    if sentiment == "mixed":
        return rng.choices(["2", "3", "4"], weights=[0.2, 0.6, 0.2])[0]
    if sentiment == "request":
        return rng.choices(["3", "4"], weights=[0.7, 0.3])[0]
    return rng.choices(["1", "2", "3"], weights=[0.45, 0.35, 0.2])[0]


def build_title(rng: random.Random, node: dict[str, Any], profile: dict[str, Any]) -> str:
    if profile["source_type"] == "support_chat_summary" and rng.random() < 0.5:
        return ""
    if rng.random() < 0.05:
        return ""
    label = node["display_name"]
    return rng.choice(
        [
            f"{label} issue",
            f"{label} feedback",
            f"Problem with {label}",
            f"{label} not working",
            f"Feedback on {label}",
            f"{label} experience",
        ]
    )


def random_datetime(rng: random.Random) -> datetime:
    span = int((END_DATE - START_DATE).total_seconds())
    return START_DATE + timedelta(seconds=rng.randint(0, span))


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate(rows: int, minimum: int, seed: int, taxonomy_path: Path) -> list[dict[str, str]]:
    rng = random.Random(seed)
    feature_nodes, module_of, _ = load_feature_nodes(taxonomy_path)
    node_by_id = {node["node_id"]: node for node in feature_nodes}

    missing = [node["node_id"] for node in feature_nodes if node["node_id"] not in PROBLEMS]
    if missing:
        raise SystemExit("missing problem templates for: " + ", ".join(missing))
    unknown = [node_id for node_id in PROBLEMS if node_id not in node_by_id]
    if unknown:
        raise SystemExit("problem templates reference unknown nodes: " + ", ".join(unknown))

    counts = allocate_counts(feature_nodes, module_of, MODULE_WEIGHTS, rows, minimum)
    node_sequence: list[str] = []
    for node_id, count in counts.items():
        node_sequence.extend([node_id] * count)
    rng.shuffle(node_sequence)

    customers = [f"SYN-CUST-{index:05d}" for index in range(1, 3001)]
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records: list[dict[str, str]] = []

    for node_id in node_sequence:
        node = node_by_id[node_id]
        profile = weighted_choice(rng, SOURCE_PROFILES)
        context = build_context(rng)

        customer = rng.choice(customers)
        submitted = random_datetime(rng)
        platform = profile["platform"]
        version = rng.choice(APP_VERSIONS) if rng.random() < profile["version_prob"] else ""

        duplicate_roll = rng.random()
        if duplicate_roll < 0.04 and history[node_id]:
            prior = rng.choice(history[node_id])
            text = prior["text"]
            customer = prior["customer"]
            submitted = prior["submitted"] + timedelta(days=rng.randint(0, 25), hours=rng.randint(0, 23))
            submitted = min(submitted, END_DATE)
            language = prior["language"]
            sentiment = prior["sentiment"]
        elif duplicate_roll < 0.07 and history[node_id]:
            prior = rng.choice(history[node_id])
            suffix = rng.choice(["Still not resolved.", "Same issue again today.", "This is the second time."])
            text = f"{prior['text']} {suffix}"
            customer = prior["customer"]
            submitted = prior["submitted"] + timedelta(days=rng.randint(0, 25), hours=rng.randint(0, 23))
            submitted = min(submitted, END_DATE)
            language = prior["language"]
            sentiment = prior["sentiment"]
        else:
            text, language, sentiment = compose_text(rng, node, feature_nodes, context)

        record = {
            "feedback_id": "",
            "submitted_at": iso_z(submitted),
            "source_type": profile["source_type"],
            "source_channel": profile["source_channel"],
            "platform": platform,
            "app_version": version,
            "language": language,
            "synthetic_customer_ref": customer,
            "rating_1_to_5": pick_rating(rng, sentiment, profile),
            "feedback_title": build_title(rng, node, profile),
            "feedback_text": text,
            "is_synthetic": "true",
            "_node_id": node_id,
        }
        records.append(record)
        history[node_id].append(
            {
                "text": text,
                "customer": customer,
                "submitted": submitted,
                "language": language,
                "sentiment": sentiment,
            }
        )

    rng.shuffle(records)
    for index, record in enumerate(records, start=1):
        record["feedback_id"] = f"FB-{index:06d}"

    return records


def validate(records: list[dict[str, str]], feature_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    node_counts = Counter(record["_node_id"] for record in records)
    missing = [node["node_id"] for node in feature_nodes if node_counts.get(node["node_id"], 0) == 0]
    if missing:
        raise SystemExit("nodes without feedback: " + ", ".join(missing))

    ids = [record["feedback_id"] for record in records]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate feedback_id values generated")

    lengths = [len(record["feedback_text"]) for record in records]
    if min(lengths) < 20:
        raise SystemExit("generated feedback_text is too short")
    if max(lengths) > 5000:
        raise SystemExit("generated feedback_text exceeds the configured maximum")

    texts = [record["feedback_text"] for record in records]
    return {
        "node_counts": node_counts,
        "distinct_texts": len(set(texts)),
        "exact_duplicate_texts": len(texts) - len(set(texts)),
        "min_length": min(lengths),
        "max_length": max(lengths),
        "mean_length": round(sum(lengths) / len(lengths), 1),
        "source_types": Counter(record["source_type"] for record in records),
        "languages": Counter(record["language"] for record in records),
        "ratings": Counter(record["rating_1_to_5"] or "missing" for record in records),
        "platforms": Counter(record["platform"] for record in records),
    }


def write_csv(records: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=15000)
    parser.add_argument("--min-per-node", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    feature_nodes, _, version = load_feature_nodes(args.taxonomy)
    records = generate(args.rows, args.min_per_node, args.seed, args.taxonomy)
    summary = validate(records, feature_nodes)
    write_csv(records, args.out)

    print(f"taxonomy version: {version}")
    print(f"feature nodes covered: {len(summary['node_counts'])}/{len(feature_nodes)}")
    print(f"rows written: {len(records)} -> {args.out}")
    print(f"text length min/mean/max: {summary['min_length']}/{summary['mean_length']}/{summary['max_length']}")
    print(f"distinct texts: {summary['distinct_texts']} (exact duplicate texts: {summary['exact_duplicate_texts']})")
    for label in ("source_types", "platforms", "languages", "ratings"):
        print(f"{label}: {dict(summary[label].most_common())}")
    per_module = Counter()
    for node in feature_nodes:
        per_module[node["node_id"].split(".")[0]] += summary["node_counts"][node["node_id"]]
    print(f"rows per module: {dict(sorted(per_module.items()))}")


if __name__ == "__main__":
    main()
