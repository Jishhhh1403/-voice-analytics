from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    key: str
    label: str
    patterns: tuple[str, ...]
    node_hint: str | None = None


@dataclass(frozen=True)
class Aspect:
    key: str
    label: str
    node_id: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class Symptom:
    key: str
    label: str
    category: str
    patterns: tuple[str, ...]


def rx(*patterns: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b", re.IGNORECASE)


INTENTS: list[Intent] = [
    Intent("verify_otp", "verify OTP", (r"otp", r"one[- ]time password", r"verification code", r"security code"), "auth.otp"),
    Intent("biometric_login", "use biometric login", (r"biometric", r"fingerprint", r"face id", r"face recognition", r"face unlock"), "auth.biometric"),
    Intent("reset_password", "reset password", (r"reset (?:my )?password", r"forgot (?:my )?password", r"change (?:my )?password", r"password recovery"), "auth.password_reset"),
    Intent("login", "log in", (r"log ?in", r"sign ?in", r"access (?:my )?account", r"enter (?:my )?password"), "auth.login"),
    Intent("manage_session", "stay signed in", (r"session", r"stay (?:signed|logged) in", r"signed out", r"logged out", r"re-?authenticate"), "auth.session"),
    Intent("transfer_funds", "transfer funds", (r"fund transfer", r"money transfer", r"transfer (?:money|funds|amount)", r"send money", r"send funds", r"remittance"), "payments.status"),
    Intent("upi_payment", "make a UPI payment", (r"upi", r"qr payment", r"merchant payment", r"vpa"), "payments.upi"),
    Intent("imps_transfer", "make an IMPS transfer", (r"imps",), "payments.imps"),
    Intent("neft_transfer", "make a NEFT transfer", (r"neft",), "payments.neft"),
    Intent("rtgs_transfer", "make an RTGS transfer", (r"rtgs",), "payments.rtgs"),
    Intent("check_refund", "track a refund", (r"refund", r"reversal", r"money back"), "payments.refund"),
    Intent("pay_bill", "pay a bill", (r"bill payment", r"pay (?:a |the )?bill", r"utility bill", r"electricity bill", r"credit card bill"), "payments.bill_payment"),
    Intent("recharge", "complete a recharge", (r"recharge", r"prepaid", r"dth"), "payments.recharge"),
    Intent("edit_beneficiary", "edit a beneficiary", (r"edit (?:the |a |my )?(?:saved )?(?:beneficiary|payee)", r"update (?:the |a |my )?(?:saved )?(?:beneficiary|payee)", r"change (?:the |a |my )?(?:beneficiary|payee)", r"updating (?:a |the )?(?:saved )?beneficiary"), "beneficiary.edit"),
    Intent("delete_beneficiary", "delete a beneficiary", (r"(?:delete|deleting|deleted|remove|removing|removed) (?:the |an? |old |saved )?(?:beneficiary|payee)",), "beneficiary.delete"),
    Intent("add_beneficiary", "add a beneficiary", (r"add (?:a )?(?:new )?beneficiary", r"add (?:a )?(?:new )?payee", r"register (?:a )?beneficiary", r"new beneficiary", r"new payee"), "beneficiary.add"),
    Intent("verify_beneficiary", "verify a beneficiary", (r"beneficiary verification", r"verify (?:the )?beneficiary", r"cooling[- ]off"), "beneficiary.verify"),
    Intent("select_beneficiary", "select a beneficiary", (r"select (?:a )?beneficiary", r"choose (?:a )?payee", r"saved beneficiaries"), "beneficiary.select"),
    Intent("view_balance", "check the balance", (r"balance", r"available funds"), "accounts.balance"),
    Intent("view_transactions", "view transaction history", (r"transaction history", r"recent transactions", r"account summary", r"transaction list", r"mini statement"), "accounts.history"),
    Intent("generate_statement", "generate a statement", (r"generate (?:the |a |my )?(?:account |pdf )?statement", r"statement generation", r"generat(?:e|ing) (?:the )?pdf statement", r"statement (?:fails?|is generated)"), "statements.generate"),
    Intent("share_statement", "share a statement", (r"share (?:or email )?(?:my |the )?(?:account )?statement", r"share statement", r"shared statement", r"sending the statement", r"send (?:the |my )?statement", r"statement by email"), "statements.share"),
    Intent("download_statement", "download a statement", (r"download (?:my |the |an? )?(?:account )?statement", r"account statement", r"pdf statement", r"bank statement", r"statement download"), "statements.download"),
    Intent("manage_card", "manage a card", (r"debit card", r"credit card", r"card control", r"card setting", r"card payment", r"card transaction"), "cards.controls"),
    Intent("block_card", "block or unblock a card", (r"block (?:my )?(?:debit |credit )?card", r"unblock (?:my )?(?:debit |credit )?card", r"report (?:my )?card as lost", r"lost card"), "cards.block"),
    Intent("replace_card", "replace a card", (r"replace (?:my )?card", r"replacement card", r"card replacement", r"card delivery"), "cards.replacement"),
    Intent("change_limit", "change a card limit", (r"atm (?:withdrawal )?limit", r"withdrawal limit", r"card limit", r"transaction limit", r"payment limit"), "cards.limits"),
    Intent("renew_deposit", "renew a deposit", (r"renew (?:my |the )?(?:fixed |term )?deposit", r"auto[- ]renewal", r"renewal (?:interest )?(?:rate|option)?", r"renew(?:ed)? (?:my )?deposit"), "deposits.renewal"),
    Intent("book_deposit", "book a fixed deposit", (r"book (?:a )?(?:fixed |term )?deposit", r"fixed deposit", r"book (?:an )?fd", r"interest rate"), "deposits.booking"),
    Intent("view_deposit", "view deposit details", (r"maturity date", r"maturity value", r"deposit advice", r"deposit statement", r"interest (?:will be )?paid"), "deposits.maturity"),
    Intent("close_deposit", "close a deposit early", (r"premature closure", r"close (?:the )?deposit", r"early closure", r"penalty"), "deposits.premature_closure"),
    Intent("apply_loan", "apply for a loan", (r"loan application", r"apply (?:for )?(?:a )?loan", r"loan eligibility", r"loan form", r"pre[- ]approved", r"loan offer"), "loans.application"),
    Intent("view_loan_status", "track a loan application", (r"loan status", r"loan approval", r"application status", r"loan tracking"), "loans.status"),
    Intent("view_emi", "view EMI details", (r"emi", r"instalment", r"repayment schedule", r"repayment"), "loans.emi"),
    Intent("selfie_verification", "complete selfie verification", (r"selfie", r"face verification", r"take (?:a )?photo"), "onboarding.selfie"),
    Intent("video_kyc", "complete video KYC", (r"video kyc", r"video call", r"video verification", r"agent verification"), "onboarding.video_kyc"),
    Intent("address_verification", "verify an address", (r"address verification", r"address proof", r"update my address", r"old address", r"address update"), "onboarding.address"),
    Intent("complete_kyc", "complete KYC", (r"kyc", r"onboarding", r"identity verification", r"verify (?:my )?identity", r"account opening"), "onboarding.kyc"),
    Intent("loan_documents", "upload loan documents", (r"loan document", r"salary slip", r"documents? for (?:my )?loan", r"loan proof"), "loans.documents"),
    Intent("upload_document", "upload a document", (r"upload (?:my |the )?(?:address|id|identity)? ?(?:proof|document)", r"document upload", r"address proof", r"id proof", r"salary slip"), "onboarding.documents"),
    Intent("call_support", "call support", (r"call support", r"phone support", r"call back", r"helpline"), "support.call"),
    Intent("contact_support", "get support", (r"customer support", r"contact support", r"chat support", r"chatbot", r"agent", r"helpline", r"call support"), "support.chat"),
    Intent("raise_complaint", "raise a complaint", (r"raise (?:a )?complaint", r"complaint", r"report (?:the )?issue", r"dispute"), "support.complaint"),
    Intent("track_complaint", "track a complaint", (r"complaint reference", r"track (?:the )?complaint", r"complaint status", r"no update", r"complaint response"), "support.tracking"),
    Intent("push_notifications", "manage push notifications", (r"push notification", r"push alert", r"app notification", r"push message"), "notifications.push"),
    Intent("sms_alerts", "manage SMS alerts", (r"sms alert", r"sms message", r"sms notification", r"text message", r"alerts? by sms"), "notifications.sms"),
    Intent("email_alerts", "manage email alerts", (r"email alert", r"email notification", r"email statement", r"statement by email"), "notifications.email"),
    Intent("manage_notifications", "manage notifications", (r"notification", r"alert", r"sms", r"push", r"email alert"), "notifications"),
    Intent("view_home", "use the home screen", (r"home screen", r"back button", r"dashboard label", r"home page"), "navigation.home"),
    Intent("search_feature", "find an app feature", (r"find (?:the )?option", r"find (?:a )?feature", r"search", r"locate", r"menu", r"home screen", r"back button"), "navigation.search"),
    Intent("view_profile", "manage profile", (r"profile", r"address", r"account details", r"personal details"), "accounts.details"),
]

ASPECTS: list[Aspect] = [
    Aspect("otp", "OTP verification", "auth.otp", (r"otp", r"one[- ]time password", r"verification code", r"security code", r"sms code")),
    Aspect("biometric", "biometric login", "auth.biometric", (r"biometric", r"fingerprint", r"face id", r"face recognition", r"face unlock")),
    Aspect("password_reset", "password reset", "auth.password_reset", (r"reset (?:my )?password", r"forgot (?:my )?password", r"change (?:my )?password", r"password recovery")),
    Aspect("login", "login", "auth.login", (r"log ?in", r"sign ?in", r"password", r"access (?:my )?account")),
    Aspect("session", "session", "auth.session", (r"session", r"signed out", r"logged out", r"logs me out", r"re-?authenticate", r"expires?")),
    Aspect("upi", "UPI payment", "payments.upi", (r"upi", r"qr payment", r"merchant payment", r"vpa")),
    Aspect("imps", "IMPS transfer", "payments.imps", (r"imps",)),
    Aspect("neft", "NEFT transfer", "payments.neft", (r"neft",)),
    Aspect("rtgs", "RTGS transfer", "payments.rtgs", (r"rtgs",)),
    Aspect("transfer_status", "transfer status", "payments.status", (r"fund transfer", r"money transfer", r"transfer status", r"pending status", r"transfer", r"send money", r"status", r"submitted", r"draft", r"confirmation", r"reference number", r"transaction reference", r"retry")),
    Aspect("bill_payment", "bill payment", "payments.bill_payment", (r"bill payment", r"pay (?:a |the )?bill", r"utility bill", r"electricity bill", r"credit card bill", r"biller")),
    Aspect("recharge", "recharge", "payments.recharge", (r"recharge", r"prepaid", r"dth")),
    Aspect("refund", "refund", "payments.refund", (r"refund", r"reversal", r"money back")),
    Aspect("beneficiary_add", "beneficiary registration", "beneficiary.add", (r"add (?:a )?(?:new )?beneficiary", r"add (?:a )?(?:new )?payee", r"new beneficiary", r"register (?:a )?beneficiary", r"beneficiary", r"payee", r"ifsc", r"account details")),
    Aspect("beneficiary_verify", "beneficiary verification", "beneficiary.verify", (r"beneficiary verification", r"verify (?:the )?beneficiary", r"cooling[- ]off")),
    Aspect("beneficiary_edit", "beneficiary edit", "beneficiary.edit", (r"edit (?:the |a |my )?(?:saved )?(?:beneficiary|payee)", r"update (?:the |a |my )?(?:saved )?(?:beneficiary|payee)", r"change (?:the |a |my )?(?:beneficiary|payee)", r"updating (?:a |the )?(?:saved )?beneficiary")),
    Aspect("beneficiary_delete", "beneficiary removal", "beneficiary.delete", (r"(?:delete|deleting|deleted|remove|removing|removed) (?:the |an? |old |saved )?(?:beneficiary|payee)",)),
    Aspect("beneficiary_select", "beneficiary selection", "beneficiary.select", (r"select (?:a )?(?:beneficiary|payee)", r"selecting (?:a )?beneficiary", r"choose (?:a )?payee", r"saved beneficiaries", r"saved beneficiary", r"find the beneficiary")),
    Aspect("account_overview", "account overview", "accounts.overview", (r"account overview", r"account summary", r"dashboard", r"recent transactions")),
    Aspect("balance", "balance", "accounts.balance", (r"balance", r"available balance", r"account balance")),
    Aspect("transaction_history", "transaction history", "accounts.history", (r"transaction history", r"recent transactions", r"transaction list", r"merchant description", r"transaction description")),
    Aspect("statement", "account statement", "statements.download", (r"statement", r"pdf", r"blank pdf", r"statement download")),
    Aspect("statement_range", "statement date range", "statements.range", (r"date range", r"previous financial year", r"statement period", r"custom range")),
    Aspect("statement_generate", "statement generation", "statements.generate", (r"generate (?:the |a |my )?(?:account |pdf )?statement", r"statement generation", r"generat(?:e|ing) (?:the )?pdf statement", r"statement (?:fails?|is generated)")),
    Aspect("statement_share", "statement sharing", "statements.share", (r"share (?:or email )?(?:my |the )?(?:account )?statement", r"share statement", r"shared statement", r"sending the statement", r"send (?:the |my )?statement", r"statement by email")),
    Aspect("card_controls", "card controls", "cards.controls", (r"card control", r"card setting", r"toggle", r"switch it off", r"setting")),
    Aspect("card_limits", "card limits", "cards.limits", (r"atm (?:withdrawal )?limit", r"withdrawal limit", r"card limit", r"transaction limit", r"payment limit")),
    Aspect("block_card", "card blocking", "cards.block", (r"block (?:my )?(?:debit |credit )?card", r"unblock", r"lost card", r"report (?:my )?card")),
    Aspect("card_replacement", "card replacement", "cards.replacement", (r"replacement card", r"replace (?:my )?card", r"card delivery", r"card tracking")),
    Aspect("card_online", "online card usage", "cards.online", (r"online card payment", r"online payment", r"online usage", r"online transaction", r"e-?commerce")),
    Aspect("card_usage", "card payment", "cards.usage", (r"card payment", r"card transaction", r"card declined", r"merchant")),
    Aspect("international_usage", "international card usage", "cards.international", (r"international usage", r"overseas", r"foreign transaction")),
    Aspect("deposit_booking", "fixed deposit booking", "deposits.booking", (r"book (?:a )?(?:fixed |term )?deposit", r"fixed deposit", r"book (?:an )?fd", r"interest rate")),
    Aspect("deposit_maturity", "deposit maturity", "deposits.maturity", (r"maturity", r"maturity date", r"maturity value", r"renewal", r"interest (?:will be )?paid")),
    Aspect("deposit_renewal", "deposit renewal", "deposits.renewal", (r"renew (?:my |the )?(?:fixed |term )?deposit", r"auto[- ]renewal", r"renewal (?:interest )?(?:rate|option)?", r"renew(?:ed)? (?:my )?deposit")),
    Aspect("premature_closure", "premature closure", "deposits.premature_closure", (r"premature closure", r"close (?:the )?deposit", r"early closure", r"penalty")),
    Aspect("deposit_advice", "deposit advice", "deposits.advice", (r"deposit advice", r"deposit certificate", r"deposit statement")),
    Aspect("loan_application", "loan application", "loans.application", (r"loan application", r"apply (?:for )?(?:a )?loan", r"loan form", r"application form")),
    Aspect("loan_documents", "loan documents", "loans.documents", (r"loan document", r"salary slip.*loan", r"documents? for (?:my )?loan", r"loan proof")),
    Aspect("loan_eligibility", "loan eligibility", "loans.eligibility", (r"loan eligibility", r"eligible for (?:a )?loan", r"pre[- ]approved", r"loan offer")),
    Aspect("loan_status", "loan status", "loans.status", (r"loan status", r"loan approval", r"loan tracking", r"application status")),
    Aspect("emi", "EMI", "loans.emi", (r"emi", r"instalment", r"repayment schedule", r"repayment")),
    Aspect("kyc", "KYC verification", "onboarding.kyc", (r"kyc", r"identity verification", r"verify (?:my )?identity", r"verification will take")),
    Aspect("document_upload", "document upload", "onboarding.documents", (r"document upload", r"upload (?:my |the )?(?:address|id|identity)? ?(?:proof|document)", r"uploaded document", r"id proof")),
    Aspect("onboarding", "onboarding", "onboarding.kyc", (r"onboarding", r"account opening", r"digital onboarding")),
    Aspect("selfie_verification", "selfie verification", "onboarding.selfie", (r"selfie", r"face verification", r"take (?:a )?photo")),
    Aspect("video_kyc", "video KYC", "onboarding.video_kyc", (r"video kyc", r"video call", r"video verification", r"agent verification")),
    Aspect("address_verification", "address verification", "onboarding.address", (r"address verification", r"address proof", r"update my address", r"old address", r"address update")),
    Aspect("complaint", "complaint", "support.complaint", (r"complaint", r"raise (?:a )?complaint")),
    Aspect("complaint_tracking", "complaint tracking", "support.tracking", (r"complaint reference", r"track (?:the )?complaint", r"complaint status", r"no update", r"complaint response")),
    Aspect("chat_support", "chat support", "support.chat", (r"chat", r"chatbot", r"agent", r"customer support", r"contact support")),
    Aspect("call_support", "call support", "support.call", (r"call support", r"phone support", r"call back", r"helpline")),
    Aspect("dispute", "transaction dispute", "support.dispute", (r"dispute", r"disputed (?:charge|transaction)")),
    Aspect("push_notifications", "push notifications", "notifications.push", (r"push notification", r"push alert", r"app notification", r"push message")),
    Aspect("sms_alerts", "SMS alerts", "notifications.sms", (r"sms alert", r"sms message", r"sms notification", r"text message", r"alerts? by sms")),
    Aspect("email_alerts", "email alerts", "notifications.email", (r"email alert", r"email notification", r"email statement", r"statement by email")),
    Aspect("notifications", "notifications", "notifications", (r"notification", r"alert", r"sms", r"push", r"email")),
    Aspect("notification_preferences", "notification preferences", "notifications.preferences", (r"notification preference", r"alert setting", r"mute alert", r"notification setting")),
    Aspect("navigation_home", "home screen navigation", "navigation.home", (r"home screen", r"back button", r"dashboard label", r"home page")),
    Aspect("navigation", "app navigation", "navigation.search", (r"navigation", r"menu", r"back button", r"find (?:the )?option", r"labels", r"home screen")),
    Aspect("app_performance", "app performance", "navigation.performance", (r"performance", r"slow", r"loading", r"blank screen", r"takes too long", r"responsive")),
    Aspect("app_stability", "app stability", "navigation.stability", (r"crash", r"freeze", r"frozen", r"unresponsive", r"app closes")),
    Aspect("app_labels", "labels and clarity", "navigation.labels", (r"labels", r"wording", r"unclear", r"confusing", r"clarity")),
]

SYMPTOMS: list[Symptom] = [
    Symptom("otp_timeout", "OTP times out", "timeout", (r"otp (?:step )?keeps timing out", r"otp.*tim(?:e|ing) ?out", r"verification.*tim(?:e|ing) ?out")),
    Symptom("otp_delayed", "OTP arrives late", "delayed", (r"otp.*(?:delayed|later|not arrived|no sms|did not arrive)", r"verification code.*(?:delayed|later|not arrived)", r"code.*arrived late")),
    Symptom("otp_invalid", "OTP is rejected", "invalid", (r"invalid otp", r"otp.*invalid", r"keeps saying invalid", r"wrong code", r"code.*not accepted", r"does not accept.*code")),
    Symptom("duplicate_otp", "duplicate OTP messages", "duplicate", (r"two otp", r"duplicate otp", r"multiple otp", r"more than one.*code")),
    Symptom("pending", "transaction remains pending", "pending", (r"pending", r"still shows pending", r"stuck in pending", r"not completed")),
    Symptom("delayed", "money or response is delayed", "delayed", (r"delayed", r"much later", r"several hours later", r"takes too long", r"slow", r"late")),
    Symptom("failed", "operation fails", "failure", (r"failed", r"failure", r"does not work", r"doesn't work", r"not working", r"did not work", r"not processed")),
    Symptom("declined", "payment is declined", "failure", (r"declined", r"payment.*declined", r"card.*declined")),
    Symptom("rejected", "request is rejected", "failure", (r"rejected", r"refused", r"not accepted")),
    Symptom("error", "app returns an error", "error", (r"error", r"something went wrong", r"technical error", r"keeps returning an error")),
    Symptom("timeout", "request times out", "timeout", (r"tim(?:e|ing) ?out", r"timed out", r"takes forever")),
    Symptom("blank_screen", "screen is blank", "display", (r"blank screen", r"white screen", r"blank page", r"blank pdf", r"empty pdf")),
    Symptom("loading", "screen keeps loading", "performance", (r"keeps loading", r"loading forever", r"spinner", r"stuck at \d+ percent", r"stuck at \d+%")),
    Symptom("crash", "app crashes", "stability", (r"crash(?:es|ed)?", r"app closes", r"app shuts down")),
    Symptom("freeze", "app freezes", "stability", (r"freez(?:e|es|ing)", r"frozen", r"unresponsive")),
    Symptom("slow", "app is slow", "performance", (r"slow", r"sluggish", r"takes a long time", r"takes too many taps", r"takes too long")),
    Symptom("logout", "customer is signed out", "session", (r"logs me out", r"signed out", r"logged out", r"signs me out", r"logs out")),
    Symptom("session_expired", "session expires unexpectedly", "session", (r"session (?:expires|expired|ends)", r"session.*too quickly", r"expires too quickly")),
    Symptom("reset_restart", "process restarts unexpectedly", "state", (r"restarts", r"resets", r"starts from the first step", r"returns? to the (?:home|first)")),
    Symptom("invalid_details", "valid details are rejected", "invalid", (r"ifsc.*invalid", r"correct account details", r"details.*invalid", r"invalid details")),
    Symptom("mismatch", "information does not match", "consistency", (r"different from", r"does not match", r"mismatch", r"changed on the confirmation", r"inconsistent")),
    Symptom("not_saved", "settings are not saved", "state", (r"does not save", r"not saved", r"setting.*(?:revert|reset)", r"toggle does not save")),
    Symptom("not_received", "money or message is not received", "receipt", (r"not received", r"have not received", r"did not receive", r"no sms", r"no notification", r"no update")),
    Symptom("not_submitted", "request submission is unclear", "status", (r"not sure whether.*submitted", r"cannot tell whether.*submitted", r"whether.*submitted", r"no clear confirmation", r"no confirmation")),
    Symptom("duplicate_charge", "duplicate payment or debit", "duplicate", (r"same .* twice", r"duplicate", r"twice", r"double debit", r"debited twice", r"charged twice")),
    Symptom("missing", "information is missing", "missing", (r"missing", r"does not show", r"does not include", r"not included", r"cannot find", r"not visible", r"not displayed", r"no way to", r"incomplete")),
    Symptom("unclear_status", "status or next step is unclear", "clarity", (r"does not explain", r"not clear", r"unclear", r"cannot tell", r"no clear update", r"not sure", r"confusing", r"difficult to")),
    Symptom("cannot_find", "option cannot be found", "discoverability", (r"cannot find", r"difficult to locate", r"hard to find", r"no option", r"cannot see", r"not visible")),
    Symptom("no_update", "no status update is provided", "missing", (r"no update", r"have not received an update", r"status has not changed", r"not been updated")),
    Symptom("wrong_amount", "amount is incorrect", "accuracy", (r"different from the amount", r"wrong amount", r"incorrect amount", r"changed")),
    Symptom("late_notification", "notification arrives late", "delayed", (r"alert much later", r"notification.*late", r"alert.*late", r"much later than")),
    Symptom("refund_not_visible", "refund is not visible", "missing", (r"cannot see the refund", r"refund.*not visible", r"refund.*not received", r"refund.*track")),
    Symptom("incomplete_description", "transaction description is incomplete", "clarity", (r"incomplete transaction description", r"cannot recognise the merchant", r"unrecognised merchant")),
    Symptom("security_concern", "security or access concern", "security", (r"security", r"fraud", r"unauthori[sz]ed", r"someone else")),
    Symptom("kyc_delay", "KYC verification is delayed", "delayed", (r"kyc.*(?:delay|pending|not complete|how long)", r"verification.*(?:delay|pending|how long)")),
    Symptom("document_stuck", "document upload is stuck", "blocked", (r"upload.*stuck", r"stuck at \d+ percent", r"document.*(?:fail|stuck|reject)")),
    Symptom("inaccessible", "feature is inaccessible", "blocked", (r"cannot", r"can't", r"unable to", r"not able to", r"blocked", r"restricted")),
    Symptom("difficult", "task is difficult", "effort", (r"difficult", r"hard to", r"not easy", r"takes too many taps", r"complicated")),
]

NEGATIVE = rx(
    r"cannot", r"can't", r"can not", r"unable", r"fail", r"failed", r"failure", r"error", r"errors",
    r"stuck", r"freeze", r"freezes", r"frozen", r"crash", r"crashes", r"slow", r"sluggish", r"delayed",
    r"pending", r"duplicate", r"twice", r"wrong", r"incorrect", r"invalid", r"missing", r"blank",
    r"declined", r"rejected", r"blocked", r"frustrating", r"frustrated", r"annoying", r"terrible",
    r"bad", r"worst", r"poor", r"confusing", r"confused", r"unclear", r"difficult", r"problem",
    r"issue", r"no update", r"not received", r"not working", r"not saved", r"not visible", r"timeout",
    r"times out", r"timed out", r"logs me out", r"signs me out", r"restarts", r"resets", r"painful",
    r"disappointed", r"unacceptable", r"useless", r"bug", r"broken", r"doesn't", r"does not",
    r"did not", r"not clear", r"keeps returning", r"no way", r"incomplete", r"different from",
    r"not answered", r"ignored", r"again", r"repeatedly", r"much later", r"takes too long",
    r"not sure", r"cannot tell", r"no confirmation", r"without visiting", r"eventually",
)

POSITIVE = rx(
    r"easy", r"simple", r"convenient", r"useful", r"helpful", r"clear confirmation", r"works",
    r"worked", r"quick", r"quickly", r"fast", r"smooth", r"responsive", r"clean", r"like",
    r"likes", r"good", r"great", r"excellent", r"satisfied", r"happy", r"well", r"nice",
    r"accepted", r"successful", r"success", r"completed", r"arrived quickly", r"first attempt",
    r"intuitive", r"organised", r"organized", r"makes it easy", r"impressed", r"reliable",
)

NEGATORS = rx(r"not", r"no", r"never", r"cannot", r"can't", r"doesn't", r"don't", r"isn't", r"wasn't", r"without", r"hardly", r"barely", r"failed")
INTENSIFIERS = rx(r"very", r"really", r"extremely", r"too", r"keeps", r"repeatedly", r"again", r"multiple", r"several", r"totally", r"completely")

EMOTIONS = {
    "frustration": rx(r"frustrat", r"annoy", r"angry", r"irritat", r"painful", r"unacceptable", r"tired of"),
    "confusion": rx(r"confus", r"unclear", r"not sure", r"cannot tell", r"don't understand", r"do not understand"),
    "anxiety": rx(r"worr", r"anxious", r"nervous", r"afraid", r"scared", r"stress"),
    "disappointment": rx(r"disappoint", r"let down", r"upset"),
    "satisfaction": rx(r"happy", r"satisfied", r"like", r"helpful", r"convenient", r"easy", r"impressed"),
}

EFFORT_HIGH = rx(
    r"had to contact", r"had to use another", r"had to visit", r"multiple (?:times|attempts)",
    r"more than once", r"again and again", r"repeatedly", r"took too long", r"too many taps",
    r"eventually", r"keeps", r"several attempts", r"contact (?:customer )?support",
)
EFFORT_MEDIUM = rx(r"tried", r"difficult", r"hard to", r"not easy", r"struggl", r"trouble")
EFFORT_LOW = rx(r"quickly", r"first attempt", r"easy", r"simple", r"convenient", r"without visiting", r"from home")

OUTCOME_BLOCKED = rx(r"cannot", r"can't", r"unable", r"not able", r"no option", r"blocked", r"not working", r"failed", r"declined", r"rejected", r"stuck")
OUTCOME_ABANDONED = rx(r"gave up", r"eventually had to", r"had to use another", r"had to contact", r"had to visit")
OUTCOME_WORKAROUND = rx(r"another channel", r"visited (?:a )?branch", r"called (?:the )?support", r"used the website", r"contact(?:ed)? support")
OUTCOME_FAILED = rx(r"failed", r"declined", r"rejected", r"error", r"duplicate", r"charged twice", r"did not process")
OUTCOME_COMPLETED = rx(r"worked", r"completed", r"successful", r"accepted", r"arrived quickly", r"first attempt", r"confirmed")

POSITIVE_ELABORATION = rx(r"usually works", r"works fine", r"is useful", r"are useful", r"is simple", r"is easy", r"are easy", r"looks clean", r"are convenient", r"is convenient", r"i like", r"helpful")

NODE_LABELS = {
    "authentication": "Authentication",
    "payments": "Payments",
    "beneficiaries": "Beneficiary management",
    "accounts": "Accounts",
    "statements": "Statements",
    "cards": "Cards",
    "deposits": "Deposits",
    "loans": "Loans",
    "onboarding": "Onboarding/KYC",
    "support": "Support and disputes",
    "notifications": "Notifications",
    "navigation": "Navigation and performance",
}


def match_entities(text: str, entities: list[Intent] | list[Aspect] | list[Symptom]) -> list[tuple[object, int]]:
    # Prefer the earliest, most specific anchor in the sentence. The earliest
    # match is usually the object being discussed, while later matches are often
    # incidental details (for example "statement ... transaction reference").
    matches: list[tuple[object, int]] = []
    for entity in entities:
        score = 0
        for pattern in entity.patterns:
            found = re.search(pattern, text, re.IGNORECASE)
            if found:
                candidate = (10000 - min(found.start(), 9999)) * 100 + len(found.group(0))
                score = max(score, candidate)
        if score:
            matches.append((entity, score))
    return sorted(matches, key=lambda item: item[1], reverse=True)


def best_entity(text: str, entities: list[Intent] | list[Aspect] | list[Symptom]):
    matches = match_entities(text, entities)
    return matches[0][0] if matches else None


def sentiment(text: str) -> tuple[str, float]:
    lowered = text.lower()
    positive_hits = [m.group(0) for m in POSITIVE.finditer(lowered)]
    negative_hits = [m.group(0) for m in NEGATIVE.finditer(lowered)]
    score = 0.0
    for hit in negative_hits:
        score -= 1.0
        prefix = lowered[max(0, lowered.find(hit) - 12) : lowered.find(hit)]
        if INTENSIFIERS.search(prefix):
            score -= 0.5
    for hit in positive_hits:
        score += 1.0
        prefix = lowered[max(0, lowered.find(hit) - 12) : lowered.find(hit)]
        if NEGATORS.search(prefix):
            score -= 1.0
        if INTENSIFIERS.search(prefix):
            score += 0.25
    # Mixed signals inside a clause are meaningful; keep the sign of the stronger side.
    if positive_hits and negative_hits and abs(score) <= 1.5:
        return "mixed", round(score, 2)
    if score > 0.4:
        return "positive", round(score, 2)
    if score < -0.4:
        return "negative", round(score, 2)
    return "neutral", round(score, 2)


def emotion(text: str, label: str) -> str:
    if label == "positive":
        for name in ("satisfaction",):
            if EMOTIONS[name].search(text):
                return name
    for name in ("frustration", "confusion", "anxiety", "disappointment"):
        if EMOTIONS[name].search(text):
            return name
    if label == "positive":
        return "satisfaction"
    return "none"


def effort(text: str) -> str:
    if EFFORT_HIGH.search(text):
        return "high"
    if EFFORT_MEDIUM.search(text):
        return "medium"
    if EFFORT_LOW.search(text):
        return "low"
    return "unknown"


def outcome(text: str) -> str:
    if OUTCOME_ABANDONED.search(text):
        return "abandoned"
    if OUTCOME_BLOCKED.search(text):
        return "blocked"
    if OUTCOME_FAILED.search(text):
        return "failed"
    if OUTCOME_WORKAROUND.search(text):
        return "workaround_used"
    if OUTCOME_COMPLETED.search(text):
        return "completed"
    return "unknown"
