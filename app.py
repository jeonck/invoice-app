import streamlit as st
import base64
import json
import os
import uuid
import re
import urllib.request
from io import BytesIO
from datetime import date, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from xml.sax.saxutils import escape as _xml_escape

import auth
import drive

# ---------------------------------------------------------------------------
# 한글 폰트 등록
#
# The font is bundled in fonts/ so Korean always renders, even with no
# network (Streamlit Cloud blocked the old Google Fonts download, which
# silently fell back to Helvetica and printed Korean as empty boxes).
# ---------------------------------------------------------------------------
_FONT_REGISTERED = False
_KO_FONT_NAME = "Helvetica"  # fallback
_KO_FONT_NAME_BOLD = "Helvetica-Bold"
_KO_FONT_OK = False  # True once a Korean-capable font is registered

_BUNDLED_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_FONT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "invoice-app-fonts")

# Raw files from the google/fonts repository (OFL). Used only when the
# bundled copy is missing, e.g. someone dropped app.py somewhere on its own.
_FONT_URLS = {
    "NanumGothic-Regular.ttf":
        "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/"
        "NanumGothic-Regular.ttf",
    "NanumGothic-Bold.ttf":
        "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/"
        "NanumGothic-Bold.ttf",
}

_HANGUL_RE = re.compile(r"[\uac00-\ud7a3\u3130-\u318f]")


def _download_nanum_font(dest_dir: str) -> bool:
    """Fetch NanumGothic into dest_dir. Returns True if the regular face is there."""
    regular = os.path.join(dest_dir, "NanumGothic-Regular.ttf")
    if os.path.exists(regular):
        return True
    try:
        os.makedirs(dest_dir, exist_ok=True)
        for filename, url in _FONT_URLS.items():
            target = os.path.join(dest_dir, filename)
            if os.path.exists(target):
                continue
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            # A TTF starts with 0x00010000 or "true"; anything else is an
            # error page, and writing it would poison the cache.
            if not data[:4] in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
                continue
            with open(target, "wb") as f:
                f.write(data)
    except Exception:
        pass
    return os.path.exists(regular)


def _register_korean_font():
    """Register a Korean-capable font for reportlab. Safe to call repeatedly."""
    global _FONT_REGISTERED, _KO_FONT_NAME, _KO_FONT_NAME_BOLD, _KO_FONT_OK

    if _FONT_REGISTERED:
        return _KO_FONT_OK

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    def _try_register(regular_path, bold_path):
        global _KO_FONT_NAME, _KO_FONT_NAME_BOLD
        if not regular_path or not os.path.exists(regular_path):
            return False
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", regular_path))
        except Exception:
            return False
        _KO_FONT_NAME = "KoreanFont"
        _KO_FONT_NAME_BOLD = "KoreanFont"
        if bold_path and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFontBold", bold_path))
                _KO_FONT_NAME_BOLD = "KoreanFontBold"
            except Exception:
                pass
        return True

    candidates = [
        # Bundled with the app — the path that always works.
        (os.path.join(_BUNDLED_FONT_DIR, "NanumGothic-Regular.ttf"),
         os.path.join(_BUNDLED_FONT_DIR, "NanumGothic-Bold.ttf")),
        # Previously downloaded copy.
        (os.path.join(_FONT_CACHE_DIR, "NanumGothic-Regular.ttf"),
         os.path.join(_FONT_CACHE_DIR, "NanumGothic-Bold.ttf")),
        # Common system installs (.ttc is skipped: reportlab needs a face index).
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
         "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttf",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttf"),
        ("/Library/Fonts/NanumGothic.ttf", "/Library/Fonts/NanumGothicBold.ttf"),
    ]

    for regular, bold in candidates:
        if _try_register(regular, bold):
            _FONT_REGISTERED = True
            _KO_FONT_OK = True
            return True

    # Nothing local — try the network once.
    if _download_nanum_font(_FONT_CACHE_DIR):
        if _try_register(os.path.join(_FONT_CACHE_DIR, "NanumGothic-Regular.ttf"),
                         os.path.join(_FONT_CACHE_DIR, "NanumGothic-Bold.ttf")):
            _FONT_REGISTERED = True
            _KO_FONT_OK = True
            return True

    # Final fallback — Helvetica. Korean glyphs will be missing, and the UI
    # says so rather than handing over a PDF full of empty boxes.
    _FONT_REGISTERED = True
    _KO_FONT_OK = False
    return False


def _has_hangul(value) -> bool:
    """True if any Korean character appears anywhere in the invoice data."""
    if isinstance(value, str):
        return bool(_HANGUL_RE.search(value))
    if isinstance(value, dict):
        return any(_has_hangul(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_hangul(v) for v in value)
    return False


# ---------------------------------------------------------------------------
# i18n labels
# ---------------------------------------------------------------------------
LABELS = {
    "ko": {
        "page_title": "인보이스 생성기",
        "title": "청구서 생성기",
        "subtitle": "정보를 입력하고 PDF 인보이스를 생성하세요.",
        "lang": "언어",
        "currency": "통화",
        "invoice_info": "인보이스 정보",
        "invoice_no": "인보이스 번호",
        "issue_date": "발행일",
        "due_date": "결제기한",
        "from_title": "발신자 정보 (From)",
        "to_title": "수신자 정보 (To)",
        "company": "회사명",
        "business_no": "사업자등록번호",
        "address": "주소",
        "email": "이메일",
        "phone": "전화번호",
        "items_title": "품목",
        "item_name": "품목명",
        "qty": "수량",
        "unit_price": "단가",
        "amount": "금액",
        "add_item": "품목 추가",
        "remove_item": "삭제",
        "subtotal": "소계",
        "tax_rate": "세율 (%)",
        "tax": "세금",
        "total": "합계",
        "payment_title": "결제 정보",
        "bank_name": "은행명",
        "account_no": "계좌번호",
        "account_holder": "예금주",
        "notes_title": "비고 / 메모",
        "notes_placeholder": "추가 메모를 입력하세요.",
        "generate": "PDF 생성",
        "download": "PDF 다운로드",
        "preview": "미리보기",
        "preview_unavailable": "미리보기를 불러오지 못했습니다. PDF 자체는 정상이니 다운로드 버튼을 사용하세요.",
        "pdf_header": "청구서",
        "pdf_footer": "감사합니다.",
        "fill_warning": "발신자, 수신자 회사명과 최소 1개 품목을 입력하세요.",
        "tab_sample": "샘플 인보이스",
        "tab_create": "인보이스 작성",
        "sample_desc": "현실적인 샘플 인보이스입니다. 참고하여 직접 작성해 보세요.",
        "use_sample": "이 샘플 내용으로 작성 시작",
        "use_sample_help": "샘플 내용이 '인보이스 작성' 탭에 그대로 채워집니다.",
        "load_sample": "샘플 채우기",
        "clear_all": "전체 지우기",
        "sample_loaded": "샘플 내용을 채웠습니다. 값을 자유롭게 수정하세요.",
        "form_cleared": "입력 내용을 모두 지웠습니다.",
        "form_hint": "아래 양식은 완성될 PDF 인보이스와 같은 순서·배치로 구성되어 있습니다. 입력하는 대로 문서가 만들어집니다.",
        "doc_caption": "아래 항목을 채우면 그대로 PDF 인보이스가 됩니다. * 는 필수 항목입니다.",
        "generated": "인보이스가 생성되었습니다.",
        "font_warning": "한글 폰트를 불러오지 못했습니다. PDF의 한글이 네모로 표시될 수 있습니다. fonts/NanumGothic-Regular.ttf 파일이 저장소에 포함되어 있는지 확인하세요.",
        "payment_notice": "계좌정보는 서버에 저장되지 않고 현재 브라우저 세션에서만 유지되며, '전체 지우기'를 누르면 즉시 삭제됩니다. 다만 생성된 PDF는 암호화되지 않으니 전달 경로에 주의하세요.",
        "login_title": "로그인",
        "login_caption": "허용된 Google 계정만 이 인보이스 도구를 사용할 수 있습니다.",
        "login_google": "Google 계정으로 로그인",
        "login_feature_doc": ("#### 📄 채우면 그대로 문서\n"
                              "입력 양식이 완성될 PDF와 같은 순서·배치입니다. "
                              "한글·영문, 원화·달러를 지원합니다."),
        "login_feature_drive": ("#### 💾 내 Drive에 저장\n"
                                "완성본은 **본인 Google Drive**에 저장됩니다. "
                                "그래서 Google 로그인이 필요하고, 이 앱은 아무것도 보관하지 않습니다."),
        "login_feature_reuse": ("#### 🔄 불러와서 재사용\n"
                                "저장한 인보이스를 불러와 수정하면 됩니다. "
                                "매달 반복되는 청구가 몇 분이면 끝납니다."),
        "login_preview_note": "아래는 이 도구로 만든 샘플 인보이스입니다.",
        "login_denied": ("{email} 계정에는 사용 권한이 없습니다. "
                         "허용 목록에 추가된 계정으로 다시 로그인하세요."),
        "login_setup_title": "Google 로그인 설정이 필요합니다",
        "login_denied_contact": "사용을 원하시면 {link} 으로 연락해 주세요.",
        "login_setup_body": ("OIDC 설정이 없어 앱을 잠근 상태입니다. Google Cloud Console에서 "
                             "OAuth 클라이언트를 만든 뒤 아래 내용을 `.streamlit/secrets.toml` "
                             "(Streamlit Cloud는 **Settings → Secrets**)에 추가하세요. "
                             "설정 방법은 README를 참고하세요."),
        "login_allowlist_title": "사용 대상이 설정되지 않았습니다",
        "login_allowlist_body": ("Google 로그인만으로는 어떤 Google 계정이든 들어올 수 있어, "
                                 "사용 대상을 정하기 전까지 앱을 잠급니다. "
                                 "방문자 누구나 쓰게 하려면 `allow_any_google_account`를, "
                                 "특정 인원만 쓰게 하려면 `allowed_emails`를 설정하세요."),
        "logout": "로그아웃",
        "sign_in": "Google 로그인",
        "sign_in_why": "로그인하면 인보이스를 내 Google Drive에 저장하고, 전에 저장한 것을 불러올 수 있습니다.",
        "anon_banner": ("로그인 없이 인보이스를 만들고 PDF로 받을 수 있습니다. "
                        "완성본을 **내 Google Drive에 저장**하려면 로그인하세요 — "
                        "저장은 본인 계정으로 이뤄지고, 이 앱은 아무것도 보관하지 않습니다."),
        "drive_sign_in_save": "로그인하고 Drive에 저장",
        "drive_sign_in_warning": ("로그인하면 페이지가 새로고침되어 **지금 입력한 내용이 사라집니다.** "
                                  "먼저 PDF를 내려받으시고, 저장까지 하실 거면 작성 전에 "
                                  "왼쪽에서 로그인하세요."),
        "drive_save": "Google Drive에 저장",
        "drive_list": "Drive에서 불러오기",
        "draft_save": "임시저장 (파일)",
        "draft_section": "임시저장 · 이어서 작업하기",
        "draft_load": "임시저장 파일 불러오기",
        "draft_loaded": "임시저장 파일을 불러왔습니다.",
        "draft_hint": ("작성 중인 내용을 JSON 파일로 내려받습니다. 로그인 없이도 쓸 수 있고, "
                       "나중에 이 파일을 올리면 그대로 이어서 작업할 수 있습니다. "
                       "파일에는 입력한 계좌정보가 그대로 들어 있으니 보관에 주의하세요."),
        "draft_unreadable": "임시저장 파일을 읽지 못했습니다. 이 앱에서 내려받은 JSON 파일인지 확인하세요.",
        "token_expired": ("Google Drive 연결이 만료되었습니다. **지금** 다시 로그인하세요 — "
                          "작성 중에 만료되면 입력한 내용이 사라집니다."),
        "sign_in_again": "다시 로그인",
        "drive_pick": "저장된 인보이스",
        "drive_load": "불러오기",
        "drive_loaded": "저장된 인보이스를 불러왔습니다. 수정 후 다시 저장하면 같은 번호의 파일을 덮어씁니다.",
        "drive_list_empty": "아직 Drive에 저장한 인보이스가 없습니다.",
        "drive_list_sign_in": "로그인하면 전에 저장한 인보이스를 불러와 그대로 수정할 수 있습니다.",
        "drive_err_unreadable": "저장된 파일을 읽지 못했습니다. 파일이 손상되었을 수 있습니다.",
        "drive_saved": "Drive의 Invoices 폴더에 PDF와 입력 데이터를 저장했습니다.",
        "drive_open": "Drive에서 열기",
        "drive_unavailable": ("Google Drive 저장은 secrets에 Drive 권한(scope)과 "
                              "expose_tokens 설정을 추가해야 사용할 수 있습니다. "
                              "설정 방법은 README를 참고하세요."),
        "drive_err_unavailable": "Drive 접근 토큰이 없습니다. 다시 로그인한 뒤 시도하세요.",
        "drive_err_expired": ("Drive 접근 권한이 만료되었습니다. 로그아웃 후 다시 "
                              "로그인하면 저장할 수 있습니다."),
        "drive_err_network": "Google Drive에 연결하지 못했습니다. 잠시 후 다시 시도하세요.",
        "drive_err_http": "Drive 저장에 실패했습니다. 잠시 후 다시 시도하세요.",
        "ph_from_company": "우리 회사 이름",
        "ph_to_company": "청구할 거래처 이름",
        "ph_bizno": "123-45-67890",
        "ph_address": "서울시 강남구 테헤란로 152, 8층",
        "ph_email": "billing@example.com",
        "ph_phone": "02-000-0000",
        "ph_item": "품목 또는 서비스 내용",
        "ph_bank": "신한은행",
        "ph_account_no": "110-000-000000",
        "ph_holder": "예금주명",
    },
    "en": {
        "page_title": "Invoice Generator",
        "title": "Invoice Generator",
        "subtitle": "Fill in the details and generate a PDF invoice.",
        "lang": "Language",
        "currency": "Currency",
        "invoice_info": "Invoice Information",
        "invoice_no": "Invoice No.",
        "issue_date": "Issue Date",
        "due_date": "Due Date",
        "from_title": "From",
        "to_title": "To",
        "company": "Company Name",
        "business_no": "Business Reg. No.",
        "address": "Address",
        "email": "Email",
        "phone": "Phone",
        "items_title": "Items",
        "item_name": "Item",
        "qty": "Qty",
        "unit_price": "Unit Price",
        "amount": "Amount",
        "add_item": "Add Item",
        "remove_item": "Remove",
        "subtotal": "Subtotal",
        "tax_rate": "Tax Rate (%)",
        "tax": "Tax",
        "total": "Total",
        "payment_title": "Payment Information",
        "bank_name": "Bank Name",
        "account_no": "Account No.",
        "account_holder": "Account Holder",
        "notes_title": "Notes / Memo",
        "notes_placeholder": "Enter additional notes.",
        "generate": "Generate PDF",
        "download": "Download PDF",
        "preview": "Preview",
        "preview_unavailable": "The preview could not load. The PDF itself is fine — use the download button.",
        "pdf_header": "INVOICE",
        "pdf_footer": "Thank you for your business!",
        "fill_warning": "Please fill in From/To company names and at least one item.",
        "tab_sample": "Sample Invoice",
        "tab_create": "Create Invoice",
        "sample_desc": "A realistic sample invoice for reference. Use it as a guide to create your own.",
        "use_sample": "Start from this sample",
        "use_sample_help": "Fills the 'Create Invoice' tab with this sample content.",
        "load_sample": "Fill sample",
        "clear_all": "Clear all",
        "sample_loaded": "Sample content loaded. Edit any field freely.",
        "form_cleared": "All fields cleared.",
        "form_hint": "The form below follows the exact order and layout of the PDF invoice it produces — what you type is what you get.",
        "doc_caption": "Fill in the fields below and they become your PDF invoice. * marks required fields.",
        "generated": "Invoice generated.",
        "font_warning": "The Korean font could not be loaded, so Korean text may appear as empty boxes in the PDF. Check that fonts/NanumGothic-Regular.ttf is present in the repository.",
        "payment_notice": "Bank details are not stored on the server — they live only in this browser session and are erased by 'Clear all'. The generated PDF itself is not encrypted, so be deliberate about how you send it.",
        "login_title": "Sign in",
        "login_caption": "This invoice tool is limited to approved Google accounts.",
        "login_google": "Sign in with Google",
        "login_feature_doc": ("#### 📄 The form is the document\n"
                              "Fields sit in the same order and place as the PDF they "
                              "produce. Korean and English, won and dollars."),
        "login_feature_drive": ("#### 💾 Saved to your own Drive\n"
                                "Finished invoices go to **your** Google Drive — which is "
                                "why it asks for a Google account, and why this app keeps "
                                "nothing."),
        "login_feature_reuse": ("#### 🔄 Reopen and reuse\n"
                                "Load a past invoice, change what differs, save it again. "
                                "A recurring bill takes minutes."),
        "login_preview_note": "Below is a sample invoice made with this tool.",
        "login_denied": ("{email} is not approved for this app. "
                         "Sign in with an address on the allowlist."),
        "login_setup_title": "Google sign-in is not configured yet",
        "login_denied_contact": "To ask for access, write to {link}.",
        "login_setup_body": ("No OIDC configuration was found, so the app is locked. Create "
                             "an OAuth client in the Google Cloud Console, then add the "
                             "settings below to `.streamlit/secrets.toml` (on Streamlit "
                             "Cloud: **Settings → Secrets**). The README has the steps."),
        "login_allowlist_title": "Nobody is configured to use this app",
        "login_allowlist_body": ("Google sign-in on its own would admit any Google account, "
                                 "so the app stays locked until it is told who it serves. "
                                 "Set `allow_any_google_account` to offer it to every "
                                 "visitor, or `allowed_emails` to keep it to a few people."),
        "logout": "Sign out",
        "sign_in": "Sign in with Google",
        "sign_in_why": "Sign in to save invoices to your own Google Drive, and reopen past ones.",
        "anon_banner": ("You can write an invoice and download the PDF without signing in. "
                        "Sign in to **save it to your own Google Drive** — the file is "
                        "created under your account, and this app keeps nothing."),
        "drive_sign_in_save": "Sign in and save to Drive",
        "drive_sign_in_warning": ("Signing in reloads the page, which **clears what you have "
                                  "typed.** Download the PDF first, or sign in from the "
                                  "sidebar before filling the form."),
        "drive_save": "Save to Google Drive",
        "drive_list": "Open from Drive",
        "draft_save": "Save draft (file)",
        "draft_section": "Drafts · pick up later",
        "draft_load": "Load a draft file",
        "draft_loaded": "Draft loaded.",
        "draft_hint": ("Downloads what you have typed as a JSON file. It works without "
                       "signing in, and uploading it later picks up where you left off. "
                       "The file holds the bank details you entered, so keep it somewhere "
                       "you would keep an invoice."),
        "draft_unreadable": "That file could not be read. Use a draft JSON downloaded from this app.",
        "token_expired": ("The connection to Google Drive has expired. Sign in again **now** — "
                          "if it expires while you are filling the form, your work goes with it."),
        "sign_in_again": "Sign in again",
        "drive_pick": "Saved invoices",
        "drive_load": "Load",
        "drive_loaded": "Loaded a saved invoice. Saving it again replaces the file with the same number.",
        "drive_list_empty": "Nothing saved to Drive yet.",
        "drive_list_sign_in": "Sign in to reopen an invoice you saved before and edit it.",
        "drive_err_unreadable": "That saved file could not be read — it may be damaged.",
        "drive_saved": "Saved the PDF and its form data to the Invoices folder in Drive.",
        "drive_open": "Open in Drive",
        "drive_unavailable": ("Saving to Google Drive needs the Drive scope and "
                              "expose_tokens added to your auth secrets. The README "
                              "has the settings."),
        "drive_err_unavailable": "No Drive token available. Sign in again and retry.",
        "drive_err_expired": ("Drive access has expired. Sign out and back in, then "
                              "save again."),
        "drive_err_network": "Could not reach Google Drive. Try again in a moment.",
        "drive_err_http": "Saving to Drive failed. Try again in a moment.",
        "ph_from_company": "Your company name",
        "ph_to_company": "Client company name",
        "ph_bizno": "EIN 00-0000000",
        "ph_address": "350 Fifth Avenue, Suite 4210, New York, NY 10118",
        "ph_email": "billing@example.com",
        "ph_phone": "+1 (000) 000-0000",
        "ph_item": "Item or service description",
        "ph_bank": "Chase Bank",
        "ph_account_no": "Routing / Account number",
        "ph_holder": "Account holder name",
    },
}

CURRENCY_SYMBOLS = {
    "KRW": "₩",
    "USD": "$",
    "EUR": "€",
    "JPY": "¥",
}


def esc(value) -> str:
    """Escape user text before it enters reportlab's paragraph markup.

    Paragraph() parses a small HTML-like language, so an unescaped value can
    style itself (<font color="white">), or make the server fetch a URL
    (<img src="http://...">) while the PDF is being built.
    """
    return _xml_escape(str(value))


def esc_lines(value) -> str:
    """Escape user text and keep its line breaks as paragraph line breaks."""
    return "<br/>".join(esc(line) for line in str(value).splitlines())


def safe_draft_filename(invoice_no: str) -> str:
    """A draft file named after the invoice, minus anything path-like."""
    stem = safe_pdf_filename(invoice_no, "invoice")[:-4]
    return f"draft-{stem}.json"


def safe_pdf_filename(stem: str, fallback: str = "invoice") -> str:
    """Build a download filename that cannot carry a path or control chars."""
    cleaned = re.sub(r"[^\w.-]+", "-", str(stem), flags=re.UNICODE).strip("-. ")
    return f"{cleaned or fallback}.pdf"


def fmt_money(value: float, symbol: str) -> str:
    """Format a number with currency symbol."""
    if symbol in ("₩", "¥"):
        return f"{symbol}{value:,.0f}"
    return f"{symbol}{value:,.2f}"


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------
def generate_pdf(data: dict, lang: str, currency: str) -> bytes:
    font_ok = _register_korean_font()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    L = LABELS[lang]
    sym = CURRENCY_SYMBOLS[currency]

    # Helvetica has neither Hangul nor the won sign, so switch to the
    # embedded font whenever either can show up — an English invoice billed
    # in KRW, or an English UI with a Korean company name typed into it.
    needs_unicode = lang == "ko" or sym == "\u20a9" or _has_hangul(data)
    if needs_unicode and font_ok:
        fn = _KO_FONT_NAME
        fn_bold = _KO_FONT_NAME_BOLD
    else:
        fn = "Helvetica"
        fn_bold = "Helvetica-Bold"

    styles = getSampleStyleSheet()

    s_title = ParagraphStyle("Title2", parent=styles["Title"], fontName=fn_bold, fontSize=22)
    s_heading = ParagraphStyle("Heading", fontName=fn_bold, fontSize=11, spaceAfter=4)
    s_normal = ParagraphStyle("Norm", fontName=fn, fontSize=9, leading=12)
    s_normal_r = ParagraphStyle("NormR", parent=s_normal, alignment=TA_RIGHT)
    s_small = ParagraphStyle("Small", fontName=fn, fontSize=8, leading=10, textColor=colors.grey)
    s_footer = ParagraphStyle("Footer", fontName=fn, fontSize=9, alignment=TA_CENTER,
                              textColor=colors.grey)

    elements = []

    # --- Header ---
    elements.append(Paragraph(L["pdf_header"], s_title))
    elements.append(Spacer(1, 4 * mm))

    # Invoice meta row
    meta_data = [
        [Paragraph(f"<b>{L['invoice_no']}:</b> {esc(data['invoice_no'])}", s_normal),
         Paragraph(f"<b>{L['issue_date']}:</b> {esc(data['issue_date'])}", s_normal),
         Paragraph(f"<b>{L['due_date']}:</b> {esc(data['due_date'])}", s_normal)],
    ]
    meta_table = Table(meta_data, colWidths=[doc.width / 3] * 3)
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 6 * mm))

    # --- From / To ---
    def _party_block(title, d):
        lines = [f"<b>{title}</b>"]
        if d.get("company"):
            lines.append(esc(d["company"]))
        if d.get("business_no"):
            lines.append(f"{L['business_no']}: {esc(d['business_no'])}")
        if d.get("address"):
            lines.append(esc(d["address"]))
        if d.get("email"):
            lines.append(esc(d["email"]))
        if d.get("phone"):
            lines.append(esc(d["phone"]))
        return Paragraph("<br/>".join(lines), s_normal)

    party_table = Table(
        [[_party_block(L["from_title"], data["from"]),
          _party_block(L["to_title"], data["to"])]],
        colWidths=[doc.width / 2] * 2,
    )
    party_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Items Table ---
    header_row = [
        Paragraph(f"<b>#</b>", s_normal),
        Paragraph(f"<b>{L['item_name']}</b>", s_normal),
        Paragraph(f"<b>{L['qty']}</b>", s_normal_r),
        Paragraph(f"<b>{L['unit_price']}</b>", s_normal_r),
        Paragraph(f"<b>{L['amount']}</b>", s_normal_r),
    ]
    item_rows = [header_row]
    for idx, item in enumerate(data["items"], 1):
        item_rows.append([
            Paragraph(str(idx), s_normal),
            Paragraph(esc(item["name"]), s_normal),
            Paragraph(str(item["qty"]), s_normal_r),
            Paragraph(fmt_money(item["unit_price"], sym), s_normal_r),
            Paragraph(fmt_money(item["amount"], sym), s_normal_r),
        ])

    # Wide enough for KRW totals like \u20a912,000,000 without wrapping.
    col_w = [8 * mm, doc.width - 78 * mm, 14 * mm, 28 * mm, 28 * mm]
    items_table = Table(item_rows, colWidths=col_w, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F2F2F2"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Totals ---
    totals_data = [
        ["", Paragraph(f"<b>{L['subtotal']}</b>", s_normal_r),
         Paragraph(fmt_money(data["subtotal"], sym), s_normal_r)],
        ["", Paragraph(f"<b>{L['tax']} ({data['tax_rate']}%)</b>", s_normal_r),
         Paragraph(fmt_money(data["tax"], sym), s_normal_r)],
        ["", Paragraph(f"<b>{L['total']}</b>", s_normal_r),
         Paragraph(f"<b>{fmt_money(data['total'], sym)}</b>", s_normal_r)],
    ]
    totals_table = Table(totals_data, colWidths=[doc.width - 60 * mm, 30 * mm, 30 * mm])
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (1, 0), (-1, 0), 0.5, colors.grey),
        ("LINEABOVE", (1, 2), (-1, 2), 1, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Payment info ---
    if any(data["payment"].get(k) for k in ("bank", "account_no", "holder")):
        elements.append(Paragraph(f"<b>{L['payment_title']}</b>", s_heading))
        pay = data["payment"]
        pay_lines = []
        if pay.get("bank"):
            pay_lines.append(f"{L['bank_name']}: {esc(pay['bank'])}")
        if pay.get("account_no"):
            pay_lines.append(f"{L['account_no']}: {esc(pay['account_no'])}")
        if pay.get("holder"):
            pay_lines.append(f"{L['account_holder']}: {esc(pay['holder'])}")
        elements.append(Paragraph("<br/>".join(pay_lines), s_normal))
        elements.append(Spacer(1, 4 * mm))

    # --- Notes ---
    if data.get("notes"):
        elements.append(Paragraph(f"<b>{L['notes_title']}</b>", s_heading))
        elements.append(Paragraph(esc_lines(data["notes"]), s_normal))
        elements.append(Spacer(1, 4 * mm))

    # --- Footer ---
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(L["pdf_footer"], s_footer))

    doc.build(elements)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF preview using pdf.js (works on Streamlit Cloud / Chrome)
# ---------------------------------------------------------------------------
def render_pdf_preview(pdf_bytes: bytes, height: int = 800, unavailable: str = ""):
    """Render PDF in-browser using pdf.js canvas rendering.

    pdf.js comes from a CDN, which a corporate network or a content blocker
    can refuse. Say so in that case: an empty grey box reads as a broken app,
    and this preview is the first thing a new visitor sees.
    """
    import streamlit.components.v1 as components

    b64 = base64.b64encode(pdf_bytes).decode()
    notice = esc(unavailable or "The preview could not load. Use the download "
                                "button — the PDF itself is fine.")
    html = f"""
    <style>
      body {{ margin:0; background:#f5f5f5; }}
      .pdf-container {{ display:flex; flex-direction:column; align-items:center; gap:12px; padding:12px 0; }}
      .pdf-container canvas {{ box-shadow:0 2px 8px rgba(0,0,0,0.15); background:white; max-width:100%; height:auto; }}
      .pdf-fallback {{ font-family:sans-serif; font-size:14px; color:#666; text-align:center;
                       padding:48px 24px; line-height:1.6; }}
    </style>
    <div class="pdf-container" id="pdf-container"></div>
    <script>
      function pdfUnavailable() {{
        const box = document.getElementById('pdf-container');
        if (box && !box.querySelector('canvas')) {{
          box.innerHTML = '<div class="pdf-fallback">{notice}</div>';
        }}
      }}
    </script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"
            onerror="pdfUnavailable()"></script>
    <script>
      if (typeof pdfjsLib === 'undefined') {{ pdfUnavailable(); }}
      else {{
      pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
      (async () => {{
       try {{
        const data = atob("{b64}");
        const uint8 = new Uint8Array(data.length);
        for (let i = 0; i < data.length; i++) uint8[i] = data.charCodeAt(i);
        const pdf = await pdfjsLib.getDocument({{data: uint8}}).promise;
        const container = document.getElementById('pdf-container');
        for (let i = 1; i <= pdf.numPages; i++) {{
          const page = await pdf.getPage(i);
          const viewport = page.getViewport({{scale: 1.5}});
          const canvas = document.createElement('canvas');
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          container.appendChild(canvas);
          await page.render({{canvasContext: canvas.getContext('2d'), viewport}}).promise;
        }}
       }} catch (err) {{ pdfUnavailable(); }}
      }})();
      }}
    </script>
    """
    components.html(html, height=height, scrolling=True)


# ---------------------------------------------------------------------------
# Sample invoice data
# ---------------------------------------------------------------------------
def get_sample_data(lang: str, currency: str) -> dict:
    """Return realistic sample invoice data based on language."""
    today = date.today()
    if lang == "ko":
        items = [
            {"name": "모바일 앱 UI/UX 디자인", "qty": 1, "unit_price": 5000000, "amount": 5000000},
            {"name": "프론트엔드 개발 (React Native)", "qty": 1, "unit_price": 12000000, "amount": 12000000},
            {"name": "백엔드 API 개발", "qty": 1, "unit_price": 8000000, "amount": 8000000},
            {"name": "QA 테스트 및 버그 수정 (시간당)", "qty": 40, "unit_price": 150000, "amount": 6000000},
            {"name": "프로젝트 관리 (월단위)", "qty": 3, "unit_price": 1000000, "amount": 3000000},
        ]
        subtotal = sum(it["amount"] for it in items)
        tax_rate = 10.0
        tax = subtotal * tax_rate / 100
        return {
            "invoice_no": f"INV-{today.strftime('%Y%m%d')}-A01",
            "issue_date": str(today),
            "due_date": str(today + timedelta(days=30)),
            "from": {
                "company": "블루프린트 스튜디오",
                "business_no": "124-86-12345",
                "address": "서울시 강남구 테헤란로 152, 8층",
                "email": "billing@blueprint.kr",
                "phone": "02-555-1234",
            },
            "to": {
                "company": "그린필드 주식회사",
                "business_no": "210-81-67890",
                "address": "서울시 서초구 서초대로 321, 12층",
                "email": "accounts@greenfield.co.kr",
                "phone": "02-333-5678",
            },
            "items": items,
            "subtotal": subtotal,
            "tax_rate": tax_rate,
            "tax": tax,
            "total": subtotal + tax,
            "payment": {
                "bank": "신한은행",
                "account_no": "000-000-000000",
                "holder": "블루프린트 스튜디오",
            },
            "notes": "결제기한은 발행일로부터 30일입니다.\n계약 시 선금 50%가 지급되었습니다 (INV-20260110-A01).\n잔금은 프로젝트 납품 및 검수 완료 후 청구됩니다.",
        }
    else:
        items = [
            {"name": "Brand Identity & Logo Design", "qty": 1, "unit_price": 4500.00, "amount": 4500.00},
            {"name": "Website Design (10 pages)", "qty": 10, "unit_price": 800.00, "amount": 8000.00},
            {"name": "Frontend Development (Next.js)", "qty": 1, "unit_price": 12000.00, "amount": 12000.00},
            {"name": "CMS Integration & Training", "qty": 1, "unit_price": 2500.00, "amount": 2500.00},
            {"name": "SEO Optimization", "qty": 1, "unit_price": 1500.00, "amount": 1500.00},
        ]
        subtotal = sum(it["amount"] for it in items)
        tax_rate = 8.0
        tax = subtotal * tax_rate / 100
        return {
            "invoice_no": f"INV-{today.strftime('%Y%m%d')}-A01",
            "issue_date": str(today),
            "due_date": str(today + timedelta(days=30)),
            "from": {
                "company": "Oakwood Digital Agency",
                "business_no": "EIN 83-4027591",
                "address": "350 Fifth Avenue, Suite 4210, New York, NY 10118",
                "email": "invoices@oakwooddigital.com",
                "phone": "+1 (212) 555-0192",
            },
            "to": {
                "company": "Meridian Health Partners",
                "business_no": "EIN 47-2198635",
                "address": "200 Berkeley Street, 18th Floor, Boston, MA 02116",
                "email": "ap@meridianhealth.com",
                "phone": "+1 (617) 555-0347",
            },
            "items": items,
            "subtotal": subtotal,
            "tax_rate": tax_rate,
            "tax": tax,
            "total": subtotal + tax,
            "payment": {
                "bank": "Chase Bank",
                "account_no": "Routing: 000000000 / Acct: 0000000000",
                "holder": "Oakwood Digital Agency LLC",
            },
            "notes": "Payment due within 30 days of invoice date.\nPlease reference invoice number on all payments.\nLate payments subject to 1.5% monthly interest.",
        }


# ---------------------------------------------------------------------------
# Document-style form helpers
# ---------------------------------------------------------------------------
FORM_TEXT_KEYS = (
    "invoice_no",
    "from_company", "from_bizno", "from_addr", "from_email", "from_phone",
    "to_company", "to_bizno", "to_addr", "to_email", "to_phone",
    "bank_name", "account_no", "account_holder", "notes",
)


def _item_key(row_id: int, field: str) -> str:
    return f"item_{field}_{row_id}"


def _next_row_id() -> int:
    st.session_state.item_seq = st.session_state.get("item_seq", 0) + 1
    return st.session_state.item_seq


def _add_row(name: str = "", qty: int = 1, price: float = 0.0) -> int:
    row_id = _next_row_id()
    st.session_state.item_ids.append(row_id)
    st.session_state[_item_key(row_id, "name")] = name
    st.session_state[_item_key(row_id, "qty")] = int(qty)
    st.session_state[_item_key(row_id, "price")] = float(price)
    return row_id


def _drop_rows():
    """Remove every item row and its widget state."""
    for row_id in st.session_state.get("item_ids", []):
        for field in ("name", "qty", "price"):
            st.session_state.pop(_item_key(row_id, field), None)
    st.session_state.item_ids = []


def init_form_state():
    """Seed default values so every widget can be driven by session state."""
    ss = st.session_state
    if ss.get("form_ready"):
        return
    ss.item_seq = 0
    ss.item_ids = []
    for _ in range(3):
        _add_row()
    ss.invoice_no = f"INV-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    for key in FORM_TEXT_KEYS:
        ss.setdefault(key, "")
    ss.issue_date = date.today()
    ss.due_date = date.today() + timedelta(days=30)
    ss.tax_rate = 10.0
    ss.form_ready = True


def reset_form():
    """Callback: wipe the form back to an empty invoice."""
    _drop_rows()
    for key in FORM_TEXT_KEYS:
        st.session_state.pop(key, None)
    for key in ("issue_date", "due_date", "tax_rate", "form_ready",
                "pdf_bytes", "pdf_name", "pdf_data", "form_notice",
                "drive_result", "drive_error"):
        st.session_state.pop(key, None)
    init_form_state()
    st.session_state.form_notice = "cleared"


def _as_date(value, fallback):
    """Dates come back from Drive as whatever was in the file — be careful."""
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return fallback


def fill_form(data: dict, notice: str):
    """Put a whole invoice into the form: the sample, or one loaded back.

    Values from Drive are the app's own JSON, but they have been outside the
    app, so nothing here assumes a key exists or has the right type.
    """
    ss = st.session_state
    init_form_state()

    _drop_rows()
    for item in (data.get("items") or []):
        if not isinstance(item, dict):
            continue
        try:
            _add_row(str(item.get("name", "")),
                     int(item.get("qty", 1) or 1),
                     float(item.get("unit_price", 0) or 0))
        except (TypeError, ValueError):
            continue
    if not ss.item_ids:
        _add_row()

    ss.invoice_no = str(data.get("invoice_no", "") or "")
    ss.issue_date = _as_date(data.get("issue_date"), date.today())
    ss.due_date = _as_date(data.get("due_date"), date.today() + timedelta(days=30))
    for side in ("from", "to"):
        party = data.get(side) or {}
        party = party if isinstance(party, dict) else {}
        ss[f"{side}_company"] = str(party.get("company", "") or "")
        ss[f"{side}_bizno"] = str(party.get("business_no", "") or "")
        ss[f"{side}_addr"] = str(party.get("address", "") or "")
        ss[f"{side}_email"] = str(party.get("email", "") or "")
        ss[f"{side}_phone"] = str(party.get("phone", "") or "")
    try:
        ss.tax_rate = min(100.0, max(0.0, float(data.get("tax_rate", 10.0))))
    except (TypeError, ValueError):
        ss.tax_rate = 10.0
    payment = data.get("payment") or {}
    payment = payment if isinstance(payment, dict) else {}
    ss.bank_name = str(payment.get("bank", "") or "")
    ss.account_no = str(payment.get("account_no", "") or "")
    ss.account_holder = str(payment.get("holder", "") or "")
    ss.notes = str(data.get("notes", "") or "")
    for key in ("pdf_bytes", "pdf_name", "pdf_data", "drive_result", "drive_error"):
        ss.pop(key, None)
    ss.form_notice = notice


def load_sample_into_form(ds_lang: str):
    """Callback: fill every field with the sample invoice content."""
    fill_form(get_sample_data(ds_lang, st.session_state.get("currency_select", "KRW")),
              "sample_loaded")


def build_snapshot(ss) -> dict:
    """The form as it stands, in the same shape a saved invoice has.

    One format for both: a draft saved to disk and an invoice saved to Drive
    are the same JSON, so either can be loaded back through fill_form().
    Takes the state as an argument so it can be exercised without a session.
    """
    items = []
    for row_id in ss.get("item_ids", []):
        qty = ss.get(_item_key(row_id, "qty"), 1) or 0
        price = ss.get(_item_key(row_id, "price"), 0.0) or 0.0
        items.append({"name": ss.get(_item_key(row_id, "name"), ""),
                      "qty": qty, "unit_price": price, "amount": qty * price})
    subtotal = sum(item["amount"] for item in items)
    try:
        tax_rate = float(ss.get("tax_rate", 10.0))
    except (TypeError, ValueError):
        tax_rate = 10.0
    return {
        "invoice_no": ss.get("invoice_no", ""),
        "issue_date": str(ss.get("issue_date", date.today())),
        "due_date": str(ss.get("due_date", date.today())),
        "from": {"company": ss.get("from_company", ""),
                 "business_no": ss.get("from_bizno", ""),
                 "address": ss.get("from_addr", ""),
                 "email": ss.get("from_email", ""),
                 "phone": ss.get("from_phone", "")},
        "to": {"company": ss.get("to_company", ""),
               "business_no": ss.get("to_bizno", ""),
               "address": ss.get("to_addr", ""),
               "email": ss.get("to_email", ""),
               "phone": ss.get("to_phone", "")},
        "items": items,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax": subtotal * tax_rate / 100,
        "total": subtotal * (1 + tax_rate / 100),
        "payment": {"bank": ss.get("bank_name", ""),
                    "account_no": ss.get("account_no", ""),
                    "holder": ss.get("account_holder", "")},
        "notes": ss.get("notes", ""),
    }


def current_form_snapshot() -> dict:
    return build_snapshot(st.session_state)


def parse_draft(raw: bytes):
    """A draft file as a dict, or None when it is not one of ours."""
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_draft_file():
    """Callback: restore a draft the person downloaded earlier."""
    upload = st.session_state.get("draft_upload")
    if upload is None:
        return
    data = parse_draft(upload.getvalue())
    if data is None:
        st.session_state.draft_error = True
        return
    st.session_state.pop("draft_error", None)
    fill_form(data, "draft_loaded")


def fetch_drive_invoices():
    """Callback: ask Drive what this person has saved before."""
    try:
        st.session_state.drive_files = drive.list_invoices()
        st.session_state.pop("drive_error", None)
    except drive.DriveError as exc:
        st.session_state.drive_error = exc.code
        st.session_state.drive_files = []


def load_from_drive():
    """Callback: pull the picked invoice back into the form."""
    picked = st.session_state.get("drive_pick")
    chosen = next((f for f in st.session_state.get("drive_files", [])
                   if _drive_label(f) == picked), None)
    if not chosen:
        return
    try:
        fill_form(drive.load_invoice(chosen["id"]), "drive_loaded")
    except drive.DriveError as exc:
        st.session_state.drive_error = exc.code


def _drive_label(entry: dict) -> str:
    return f"{entry.get('name', '')}  ·  {entry.get('modified', '')}"


def append_row():
    """Callback: add one empty item row."""
    _add_row()


def remove_row(row_id: int):
    """Callback: drop a single item row."""
    if len(st.session_state.item_ids) <= 1:
        return
    st.session_state.item_ids.remove(row_id)
    for field in ("name", "qty", "price"):
        st.session_state.pop(_item_key(row_id, field), None)


FORM_CSS = """
<style>
  .inv-doc-title {
    text-align: center;
    font-size: 30px;
    font-weight: 800;
    letter-spacing: 6px;
    margin: 4px 0 2px 0;
  }
  .inv-doc-caption {
    text-align: center;
    font-size: 12px;
    opacity: 0.6;
    margin-bottom: 14px;
  }
  .inv-rule {
    border-top: 1px solid rgba(128, 128, 128, 0.28);
    margin: 14px 0 12px 0;
  }
  .inv-party-head {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding: 6px 10px;
    border-left: 4px solid #4472C4;
    background: rgba(68, 114, 196, 0.10);
    border-radius: 3px;
    margin-bottom: 8px;
  }
  .inv-party-head.to { border-left-color: #8FAADC; background: rgba(143, 170, 220, 0.14); }
  .inv-section {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin: 4px 0 8px 0;
  }
  .inv-th {
    background: #4472C4;
    color: #fff;
    font-size: 12px;
    font-weight: 700;
    padding: 7px 10px;
    border-radius: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .inv-th.r { text-align: right; }
  .inv-th.c { text-align: center; }
  .inv-th-blank {
    padding: 7px 0;
    font-size: 12px;
  }
  .inv-idx {
    text-align: center;
    font-size: 13px;
    font-weight: 600;
    opacity: 0.65;
  }
  .inv-amt {
    text-align: right;
    font-size: 15px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    padding: 0 2px;
    line-height: 1.2;
  }
  .inv-total-row {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    font-size: 14px;
    padding: 6px 2px;
    border-top: 1px solid rgba(128, 128, 128, 0.28);
    font-variant-numeric: tabular-nums;
  }
  .inv-total-row.grand {
    font-size: 19px;
    font-weight: 800;
    border-top: 2px solid #4472C4;
    padding-top: 10px;
  }
  .inv-total-row .label { opacity: 0.75; }
  .inv-total-row.grand .label { opacity: 1; }
  .inv-footer {
    text-align: center;
    font-size: 12px;
    opacity: 0.55;
    margin-top: 18px;
  }
  .inv-req { color: #d9534f; font-weight: 700; }
</style>
"""


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Invoice Generator", page_icon="📄", layout="wide")
st.markdown(FORM_CSS, unsafe_allow_html=True)

# --- Sidebar (language only until the session is signed in) ---
with st.sidebar:
    lang = st.selectbox("🌐 Language / 언어", ["한국어", "English"],
                        key="lang_select")
    lang_code = "ko" if lang == "한국어" else "en"
    L = LABELS[lang_code]

def show_what_this_is():
    """The sign-in screen's pitch: what the app makes, and why Google."""
    st.markdown("---")
    f1, f2, f3 = st.columns(3)
    for column, key in ((f1, "login_feature_doc"),
                        (f2, "login_feature_drive"),
                        (f3, "login_feature_reuse")):
        with column:
            st.markdown(L[key])

    st.markdown(f'<div class="inv-doc-caption">{L["login_preview_note"]}</div>',
                unsafe_allow_html=True)
    # No currency picker exists yet on this screen, so follow the language.
    currency = "KRW" if lang_code == "ko" else "USD"
    render_pdf_preview(
        generate_pdf(get_sample_data(lang_code, currency), lang_code, currency),
        height=560, unavailable=L["preview_unavailable"],
    )


# --- Login gate: nothing below this line renders for a signed-out visitor ---
if not auth.require_login(L, preview=show_what_this_is):
    st.stop()


def sign_out():
    """Callback: log out, leaving no invoice data behind in the session."""
    reset_form()
    st.session_state.pop("form_notice", None)
    st.logout()


with st.sidebar:
    currency = st.selectbox(f"💱 {L['currency']}",
                            list(CURRENCY_SYMBOLS.keys()), key="currency_select")
    sym = CURRENCY_SYMBOLS[currency]

    st.divider()
    if auth.is_signed_in():
        st.caption(f"👤 {auth.current_user()}")
        st.button(f"🚪 {L['logout']}", key="logout_btn",
                  on_click=sign_out, use_container_width=True)
    else:
        st.caption(L["sign_in_why"])
        if st.button(f"🔑 {L['sign_in']}", key="sidebar_login_btn",
                     use_container_width=True):
            auth.begin_sign_in()

st.title(f"📄 {L['title']}")
st.caption(L["subtitle"])

if not auth.is_signed_in() and drive.is_configured():
    st.info(f"🔑 {L['anon_banner']}")

# The token lasts about an hour and Streamlit never refreshes it. Ask once
# per session, while re-authenticating is still free.
if auth.is_signed_in() and drive.is_configured():
    if "drive_token_live" not in st.session_state:
        st.session_state.drive_token_live = drive.token_is_live()
    if not st.session_state.drive_token_live:
        st.warning(f"⏳ {L['token_expired']}")
        if st.button(f"🔑 {L['sign_in_again']}", key="reauth_btn"):
            auth.begin_sign_in()

# KRW amounts belong with the Korean sample; every other currency gets the
# international one, whatever the UI language is.
sample_dataset = "ko" if currency == "KRW" else "en"

if (lang_code == "ko" or currency == "KRW") and not _register_korean_font():
    st.warning(L["font_warning"])

init_form_state()

# --- Tabs ---
tab_sample, tab_create = st.tabs([f"📋 {L['tab_sample']}", f"✏️ {L['tab_create']}"])

# ===== TAB 1: Sample Invoice =====
with tab_sample:
    st.info(L["sample_desc"])

    st.button(f"📋 {L['use_sample']}", key="use_sample_btn",
              on_click=load_sample_into_form, args=(sample_dataset,),
              help=L["use_sample_help"])

    sample_data = get_sample_data(sample_dataset, currency)

    # Generate sample PDF automatically, in the language now selected.
    sample_pdf = generate_pdf(sample_data, lang_code, currency)
    render_pdf_preview(sample_pdf, unavailable=L["preview_unavailable"])

    st.download_button(
        label=f"⬇️ {L['download']} ({L['tab_sample']})",
        data=sample_pdf,
        file_name=safe_pdf_filename(f"sample-{sample_data['invoice_no']}"),
        mime="application/pdf",
        key="sample_download",
    )

# ===== TAB 2: Create Invoice =====
with tab_create:
    notice = st.session_state.pop("form_notice", None)
    if notice == "sample_loaded":
        st.success(f"✅ {L['sample_loaded']}")
    elif notice == "draft_loaded":
        st.success(f"✅ {L['draft_loaded']}")
    elif notice == "drive_loaded":
        st.success(f"✅ {L['drive_loaded']}")
    elif notice == "cleared":
        st.info(f"🧹 {L['form_cleared']}")

    # --- Toolbar (mirrors nothing in the PDF, kept above the document) ---
    tb1, tb2, tb3 = st.columns([1.1, 1, 3.4], vertical_alignment="center")
    with tb1:
        st.button(f"📋 {L['load_sample']}", key="load_sample_btn",
                  on_click=load_sample_into_form, args=(sample_dataset,),
                  use_container_width=True)
    with tb2:
        st.button(f"🧹 {L['clear_all']}", key="clear_form_btn",
                  on_click=reset_form, use_container_width=True)
    with tb3:
        st.caption(L["form_hint"])

    # --- Keep working later: folded away, since most sessions never need it ---
    draft_failed = bool(st.session_state.get("draft_error"))
    with st.expander(f"📝 {L['draft_section']}", expanded=draft_failed):
        st.caption(L["draft_hint"])
        dc1, dc2 = st.columns([1.2, 2.4], vertical_alignment="bottom")
        with dc1:
            st.download_button(
                f"📝 {L['draft_save']}",
                data=json.dumps(current_form_snapshot(), ensure_ascii=False,
                                indent=2).encode("utf-8"),
                file_name=safe_draft_filename(st.session_state.get("invoice_no", "")),
                mime="application/json",
                key="draft_download",
                use_container_width=True,
            )
        with dc2:
            st.file_uploader(L["draft_load"], type="json", key="draft_upload",
                             on_change=load_draft_file, label_visibility="collapsed")
        if draft_failed:
            st.caption(f"⚠️ {L['draft_unreadable']}")

    # --- Reopen a past invoice: the reason the form data is saved at all ---
    if drive.is_configured():
        if drive.is_available():
            lc1, lc2, lc3 = st.columns([1.1, 2.6, 1], vertical_alignment="bottom")
            with lc1:
                st.button(f"📂 {L['drive_list']}", key="drive_list_btn",
                          on_click=fetch_drive_invoices, use_container_width=True)
            saved = st.session_state.get("drive_files")
            if saved:
                with lc2:
                    st.selectbox(L["drive_pick"], [_drive_label(f) for f in saved],
                                 key="drive_pick", label_visibility="collapsed")
                with lc3:
                    st.button(f"↻ {L['drive_load']}", key="drive_load_btn",
                              on_click=load_from_drive, use_container_width=True)
            elif saved is not None:
                with lc2:
                    st.caption(L["drive_list_empty"])
        elif not auth.is_signed_in():
            st.caption(f"🔑 {L['drive_list_sign_in']}")

    # ================= The invoice document =================
    with st.container(border=True):
        st.markdown(f'<div class="inv-doc-title">{L["pdf_header"]}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="inv-doc-caption">{L["doc_caption"]}</div>',
                    unsafe_allow_html=True)

        # --- Invoice meta (same row order as the PDF header) ---
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            invoice_no = st.text_input(L["invoice_no"], key="invoice_no")
        with mc2:
            issue_date = st.date_input(L["issue_date"], key="issue_date")
        with mc3:
            due_date = st.date_input(L["due_date"], key="due_date")

        st.markdown('<div class="inv-rule"></div>', unsafe_allow_html=True)

        # --- From / To side by side, exactly like the PDF ---
        fc, tc = st.columns(2)
        with fc:
            st.markdown(
                f'<div class="inv-party-head">{L["from_title"]}'
                f' <span class="inv-req">*</span></div>',
                unsafe_allow_html=True)
            from_company = st.text_input(L["company"], key="from_company",
                                         placeholder=L["ph_from_company"])
            from_bizno = st.text_input(L["business_no"], key="from_bizno",
                                       placeholder=L["ph_bizno"])
            from_address = st.text_input(L["address"], key="from_addr",
                                         placeholder=L["ph_address"])
            from_email = st.text_input(L["email"], key="from_email",
                                       placeholder=L["ph_email"])
            from_phone = st.text_input(L["phone"], key="from_phone",
                                       placeholder=L["ph_phone"])
        with tc:
            st.markdown(
                f'<div class="inv-party-head to">{L["to_title"]}'
                f' <span class="inv-req">*</span></div>',
                unsafe_allow_html=True)
            to_company = st.text_input(L["company"], key="to_company",
                                       placeholder=L["ph_to_company"])
            to_bizno = st.text_input(L["business_no"], key="to_bizno",
                                     placeholder=L["ph_bizno"])
            to_address = st.text_input(L["address"], key="to_addr",
                                       placeholder=L["ph_address"])
            to_email = st.text_input(L["email"], key="to_email",
                                     placeholder=L["ph_email"])
            to_phone = st.text_input(L["phone"], key="to_phone",
                                     placeholder=L["ph_phone"])

        st.markdown('<div class="inv-rule"></div>', unsafe_allow_html=True)

        # --- Items, laid out as the PDF table ---
        st.markdown(
            f'<div class="inv-section">{L["items_title"]}'
            f' <span class="inv-req">*</span></div>',
            unsafe_allow_html=True)

        # Whole-unit currencies have no cents, so don't show any.
        whole_unit = sym in ("\u20a9", "\u00a5")
        price_fmt = "%.0f" if whole_unit else "%.2f"
        price_step = 1000.0 if whole_unit else 1.0

        ITEM_COLS = [0.5, 4.6, 1.2, 2.0, 2.0, 0.6]
        h = st.columns(ITEM_COLS, gap="small", vertical_alignment="center")
        h[0].markdown('<div class="inv-th c">#</div>', unsafe_allow_html=True)
        h[1].markdown(f'<div class="inv-th">{L["item_name"]}</div>', unsafe_allow_html=True)
        h[2].markdown(f'<div class="inv-th r">{L["qty"]}</div>', unsafe_allow_html=True)
        h[3].markdown(f'<div class="inv-th r">{L["unit_price"]}</div>', unsafe_allow_html=True)
        h[4].markdown(f'<div class="inv-th r">{L["amount"]}</div>', unsafe_allow_html=True)
        h[5].markdown('<div class="inv-th-blank">&nbsp;</div>', unsafe_allow_html=True)

        items = []
        subtotal = 0.0
        can_remove = len(st.session_state.item_ids) > 1

        for idx, row_id in enumerate(list(st.session_state.item_ids), 1):
            c = st.columns(ITEM_COLS, gap="small", vertical_alignment="center")
            c[0].markdown(f'<div class="inv-idx">{idx}</div>', unsafe_allow_html=True)
            with c[1]:
                name = st.text_input(L["item_name"], key=_item_key(row_id, "name"),
                                     label_visibility="collapsed",
                                     placeholder=L["ph_item"])
            with c[2]:
                qty = st.number_input(L["qty"], min_value=1, step=1,
                                      key=_item_key(row_id, "qty"),
                                      label_visibility="collapsed")
            with c[3]:
                unit_price = st.number_input(L["unit_price"], min_value=0.0,
                                             step=price_step, format=price_fmt,
                                             key=_item_key(row_id, "price"),
                                             label_visibility="collapsed")
            line_amount = qty * unit_price
            c[4].markdown(f'<div class="inv-amt">{fmt_money(line_amount, sym)}</div>',
                          unsafe_allow_html=True)
            with c[5]:
                st.button("✕", key=f"remove_{row_id}", help=L["remove_item"],
                          on_click=remove_row, args=(row_id,),
                          disabled=not can_remove)

            items.append({"name": name, "qty": qty,
                          "unit_price": unit_price, "amount": line_amount})
            subtotal += line_amount

        st.button(f"➕ {L['add_item']}", key="add_item_btn", on_click=append_row)

        # --- Totals, right aligned like the PDF ---
        _, totals_col = st.columns([1.6, 1])
        with totals_col:
            tax_rate = st.number_input(L["tax_rate"], min_value=0.0, max_value=100.0,
                                       step=0.5, format="%.1f", key="tax_rate")
            tax = subtotal * tax_rate / 100
            total = subtotal + tax
            st.markdown(
                f'<div class="inv-total-row"><span class="label">{L["subtotal"]}</span>'
                f'<span>{fmt_money(subtotal, sym)}</span></div>'
                f'<div class="inv-total-row"><span class="label">{L["tax"]}'
                f' ({tax_rate:g}%)</span><span>{fmt_money(tax, sym)}</span></div>'
                f'<div class="inv-total-row grand"><span class="label">{L["total"]}</span>'
                f'<span>{fmt_money(total, sym)}</span></div>',
                unsafe_allow_html=True)

        st.markdown('<div class="inv-rule"></div>', unsafe_allow_html=True)

        # --- Payment info ---
        st.markdown(f'<div class="inv-section">{L["payment_title"]}</div>',
                    unsafe_allow_html=True)
        st.caption(f"\U0001f512 {L['payment_notice']}")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            bank_name = st.text_input(L["bank_name"], key="bank_name",
                                      placeholder=L["ph_bank"])
        with pc2:
            account_no = st.text_input(L["account_no"], key="account_no",
                                       placeholder=L["ph_account_no"])
        with pc3:
            account_holder = st.text_input(L["account_holder"], key="account_holder",
                                           placeholder=L["ph_holder"])

        # --- Notes ---
        st.markdown(f'<div class="inv-section">{L["notes_title"]}</div>',
                    unsafe_allow_html=True)
        notes = st.text_area(L["notes_title"], key="notes",
                             placeholder=L["notes_placeholder"],
                             label_visibility="collapsed", height=90)

        st.markdown(f'<div class="inv-footer">{L["pdf_footer"]}</div>',
                    unsafe_allow_html=True)
    # ================= /The invoice document =================

    # --- Generate PDF ---
    filled_items = [it for it in items if it["name"].strip()]
    missing = []
    if not from_company.strip():
        missing.append(f"{L['from_title']} · {L['company']}")
    if not to_company.strip():
        missing.append(f"{L['to_title']} · {L['company']}")
    if not filled_items:
        missing.append(L["items_title"])

    if missing:
        st.caption("⚠️ " + L["fill_warning"] + " — " + ", ".join(missing))

    if st.button(f"🖨️ {L['generate']}", type="primary", use_container_width=True,
                 disabled=bool(missing)):
        invoice_data = {
            "invoice_no": invoice_no,
            "issue_date": str(issue_date),
            "due_date": str(due_date),
            "from": {
                "company": from_company,
                "business_no": from_bizno,
                "address": from_address,
                "email": from_email,
                "phone": from_phone,
            },
            "to": {
                "company": to_company,
                "business_no": to_bizno,
                "address": to_address,
                "email": to_email,
                "phone": to_phone,
            },
            "items": filled_items,
            "subtotal": sum(it["amount"] for it in filled_items),
            "tax_rate": tax_rate,
            "tax": sum(it["amount"] for it in filled_items) * tax_rate / 100,
            "total": sum(it["amount"] for it in filled_items) * (1 + tax_rate / 100),
            "payment": {
                "bank": bank_name,
                "account_no": account_no,
                "holder": account_holder,
            },
            "notes": notes,
        }

        st.session_state.pdf_bytes = generate_pdf(invoice_data, lang_code, currency)
        st.session_state.pdf_name = safe_pdf_filename(invoice_no)
        st.session_state.pdf_data = invoice_data
        st.session_state.pop("drive_result", None)
        st.session_state.pop("drive_error", None)

    # Preview + download survive reruns because the PDF lives in session state.
    if st.session_state.get("pdf_bytes"):
        st.success(f"✅ {L['generated']}")
        st.markdown(f"#### {L['preview']}")
        render_pdf_preview(st.session_state.pdf_bytes,
                           unavailable=L["preview_unavailable"])

        drive_col, dl_col = st.columns(2)
        signed_in = auth.is_signed_in()
        with drive_col:
            if drive.is_configured() and not signed_in:
                # Signing in navigates away and back, which starts a fresh
                # Streamlit session — the form does not survive it.
                if st.button(f"🔐 {L['drive_sign_in_save']}",
                             key="drive_signin_btn", type="primary",
                             use_container_width=True):
                    auth.begin_sign_in()
            elif st.button(f"💾 {L['drive_save']}", key="drive_save_btn",
                           type="primary", use_container_width=True,
                           disabled=not drive.is_available()):
                stem = st.session_state.get("pdf_name", "invoice.pdf")[:-4]
                try:
                    st.session_state.drive_result = drive.save_invoice(
                        st.session_state.pdf_bytes,
                        st.session_state.get("pdf_data", {}),
                        stem,
                        str(st.session_state.get("issue_date", date.today()))[:4],
                    )
                    st.session_state.pop("drive_error", None)
                except drive.DriveError as exc:
                    st.session_state.drive_error = exc.code
                    if exc.code == "expired":
                        st.session_state.drive_token_live = False
                    st.session_state.pop("drive_result", None)
                st.rerun()
        with dl_col:
            st.download_button(
                label=f"⬇️ {L['download']}",
                data=st.session_state.pdf_bytes,
                file_name=st.session_state.get("pdf_name", "invoice.pdf"),
                mime="application/pdf",
                key="created_download",
                use_container_width=True,
            )

        if not drive.is_configured():
            st.caption(f"ℹ️ {L['drive_unavailable']}")
        elif not signed_in:
            st.caption(f"⚠️ {L['drive_sign_in_warning']}")

        saved = st.session_state.get("drive_result")
        if saved:
            link = saved["pdf"].get("webViewLink")
            message = f"✅ {L['drive_saved']}"
            st.success(f"{message} — [{L['drive_open']}]({link})" if link else message)

        failure = st.session_state.get("drive_error")
        if failure:
            st.error(f"⚠️ {L.get('drive_err_' + failure, L['drive_err_http'])}")
