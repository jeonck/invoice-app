import streamlit as st
import base64
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
        "company": "회사명 / 이름",
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
        "company": "Company / Name",
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
        [Paragraph(f"<b>{L['invoice_no']}:</b> {data['invoice_no']}", s_normal),
         Paragraph(f"<b>{L['issue_date']}:</b> {data['issue_date']}", s_normal),
         Paragraph(f"<b>{L['due_date']}:</b> {data['due_date']}", s_normal)],
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
            lines.append(d["company"])
        if d.get("business_no"):
            lines.append(f"{L['business_no']}: {d['business_no']}")
        if d.get("address"):
            lines.append(d["address"])
        if d.get("email"):
            lines.append(d["email"])
        if d.get("phone"):
            lines.append(d["phone"])
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
            Paragraph(item["name"], s_normal),
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
            pay_lines.append(f"{L['bank_name']}: {pay['bank']}")
        if pay.get("account_no"):
            pay_lines.append(f"{L['account_no']}: {pay['account_no']}")
        if pay.get("holder"):
            pay_lines.append(f"{L['account_holder']}: {pay['holder']}")
        elements.append(Paragraph("<br/>".join(pay_lines), s_normal))
        elements.append(Spacer(1, 4 * mm))

    # --- Notes ---
    if data.get("notes"):
        elements.append(Paragraph(f"<b>{L['notes_title']}</b>", s_heading))
        elements.append(Paragraph(data["notes"], s_normal))
        elements.append(Spacer(1, 4 * mm))

    # --- Footer ---
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(L["pdf_footer"], s_footer))

    doc.build(elements)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF preview using pdf.js (works on Streamlit Cloud / Chrome)
# ---------------------------------------------------------------------------
def render_pdf_preview(pdf_bytes: bytes, height: int = 800):
    """Render PDF in-browser using pdf.js canvas rendering."""
    import streamlit.components.v1 as components

    b64 = base64.b64encode(pdf_bytes).decode()
    html = f"""
    <style>
      body {{ margin:0; background:#f5f5f5; }}
      .pdf-container {{ display:flex; flex-direction:column; align-items:center; gap:12px; padding:12px 0; }}
      .pdf-container canvas {{ box-shadow:0 2px 8px rgba(0,0,0,0.15); background:white; max-width:100%; height:auto; }}
    </style>
    <div class="pdf-container" id="pdf-container"></div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <script>
      pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
      (async () => {{
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
      }})();
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
                "account_no": "110-432-789012",
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
                "account_no": "Routing: 021000021 / Acct: 483927105",
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
                "pdf_bytes", "pdf_name", "form_notice"):
        st.session_state.pop(key, None)
    init_form_state()
    st.session_state.form_notice = "cleared"


def load_sample_into_form(ds_lang: str):
    """Callback: fill every field with the sample invoice content."""
    data = get_sample_data(ds_lang, st.session_state.get("currency_select", "KRW"))
    ss = st.session_state
    init_form_state()

    _drop_rows()
    for item in data["items"]:
        _add_row(item["name"], item["qty"], item["unit_price"])

    ss.invoice_no = data["invoice_no"]
    ss.issue_date = date.fromisoformat(data["issue_date"])
    ss.due_date = date.fromisoformat(data["due_date"])
    for side, prefix in (("from", "from"), ("to", "to")):
        party = data[side]
        ss[f"{prefix}_company"] = party["company"]
        ss[f"{prefix}_bizno"] = party["business_no"]
        ss[f"{prefix}_addr"] = party["address"]
        ss[f"{prefix}_email"] = party["email"]
        ss[f"{prefix}_phone"] = party["phone"]
    ss.tax_rate = float(data["tax_rate"])
    ss.bank_name = data["payment"]["bank"]
    ss.account_no = data["payment"]["account_no"]
    ss.account_holder = data["payment"]["holder"]
    ss.notes = data["notes"]
    ss.pop("pdf_bytes", None)
    ss.pop("pdf_name", None)
    ss.form_notice = "sample_loaded"


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

# --- Sidebar ---
with st.sidebar:
    lang = st.selectbox("🌐 Language / 언어", ["한국어", "English"],
                        key="lang_select")
    lang_code = "ko" if lang == "한국어" else "en"
    L = LABELS[lang_code]

    currency = st.selectbox(f"💱 {L['currency']}",
                            list(CURRENCY_SYMBOLS.keys()), key="currency_select")
    sym = CURRENCY_SYMBOLS[currency]

st.title(f"📄 {L['title']}")
st.caption(L["subtitle"])

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
    render_pdf_preview(sample_pdf)

    st.download_button(
        label=f"⬇️ {L['download']} ({L['tab_sample']})",
        data=sample_pdf,
        file_name=f"sample-{sample_data['invoice_no']}.pdf",
        mime="application/pdf",
        key="sample_download",
    )

# ===== TAB 2: Create Invoice =====
with tab_create:
    notice = st.session_state.pop("form_notice", None)
    if notice == "sample_loaded":
        st.success(f"✅ {L['sample_loaded']}")
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
        st.session_state.pdf_name = f"{invoice_no or 'invoice'}.pdf"

    # Preview + download survive reruns because the PDF lives in session state.
    if st.session_state.get("pdf_bytes"):
        st.success(f"✅ {L['generated']}")
        st.markdown(f"#### {L['preview']}")
        render_pdf_preview(st.session_state.pdf_bytes)
        st.download_button(
            label=f"⬇️ {L['download']}",
            data=st.session_state.pdf_bytes,
            file_name=st.session_state.get("pdf_name", "invoice.pdf"),
            mime="application/pdf",
            key="created_download",
        )
