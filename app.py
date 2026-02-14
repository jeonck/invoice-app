import streamlit as st
import base64
import os
import uuid
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
# 한글 폰트 등록 (런타임)
# ---------------------------------------------------------------------------
_FONT_REGISTERED = False
_KO_FONT_NAME = "Helvetica"  # fallback
_KO_FONT_NAME_BOLD = "Helvetica-Bold"


def _register_korean_font():
    """Register a Korean-capable font for reportlab."""
    global _FONT_REGISTERED, _KO_FONT_NAME, _KO_FONT_NAME_BOLD

    if _FONT_REGISTERED:
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Candidate Korean font paths (macOS / Linux common locations)
    candidates = [
        # macOS system fonts
        "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/NanumGothic.ttf",
        "/Library/Fonts/NanumGothicBold.ttf",
        # Linux common
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/nanum/NanumGothic.ttf",
    ]

    # Also try NanumGothic from user home (downloaded at runtime)
    home = os.path.expanduser("~")
    local_font = os.path.join(home, ".fonts", "NanumGothic.ttf")
    local_font_bold = os.path.join(home, ".fonts", "NanumGothicBold.ttf")
    candidates.insert(0, local_font)

    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", path))
                _KO_FONT_NAME = "KoreanFont"
                # Try bold variant
                bold_path = path.replace("NanumGothic.ttf", "NanumGothicBold.ttf")
                if bold_path != path and os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont("KoreanFontBold", bold_path))
                    _KO_FONT_NAME_BOLD = "KoreanFontBold"
                else:
                    _KO_FONT_NAME_BOLD = "KoreanFont"
                _FONT_REGISTERED = True
                return
            except Exception:
                continue

    # Fallback: try CID font for Korean
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        _KO_FONT_NAME = "HYSMyeongJo-Medium"
        _KO_FONT_NAME_BOLD = "HYSMyeongJo-Medium"
        _FONT_REGISTERED = True
    except Exception:
        # Final fallback — Helvetica (Korean glyphs will be missing)
        _FONT_REGISTERED = True


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
    _register_korean_font()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    L = LABELS[lang]
    sym = CURRENCY_SYMBOLS[currency]

    # Choose font based on language
    if lang == "ko":
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

    col_w = [8 * mm, doc.width - 68 * mm, 15 * mm, 22 * mm, 23 * mm]
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
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Invoice Generator", page_icon="📄", layout="wide")

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

# --- Invoice Meta ---
st.subheader(L["invoice_info"])
mc1, mc2, mc3 = st.columns(3)
with mc1:
    default_inv_no = f"INV-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    invoice_no = st.text_input(L["invoice_no"], value=default_inv_no)
with mc2:
    issue_date = st.date_input(L["issue_date"], value=date.today())
with mc3:
    due_date = st.date_input(L["due_date"], value=date.today() + timedelta(days=30))

# --- From ---
st.subheader(L["from_title"])
fc1, fc2 = st.columns(2)
with fc1:
    from_company = st.text_input(L["company"], key="from_company")
    from_bizno = st.text_input(L["business_no"], key="from_bizno")
    from_address = st.text_input(L["address"], key="from_addr")
with fc2:
    from_email = st.text_input(L["email"], key="from_email")
    from_phone = st.text_input(L["phone"], key="from_phone")

# --- To ---
st.subheader(L["to_title"])
tc1, tc2 = st.columns(2)
with tc1:
    to_company = st.text_input(L["company"], key="to_company")
    to_bizno = st.text_input(L["business_no"], key="to_bizno")
    to_address = st.text_input(L["address"], key="to_addr")
with tc2:
    to_email = st.text_input(L["email"], key="to_email")
    to_phone = st.text_input(L["phone"], key="to_phone")

# --- Items ---
st.subheader(L["items_title"])

if "item_count" not in st.session_state:
    st.session_state.item_count = 1

items = []
subtotal = 0.0

for i in range(st.session_state.item_count):
    ic1, ic2, ic3, ic4, ic5 = st.columns([4, 1, 2, 2, 0.5])
    with ic1:
        name = st.text_input(L["item_name"], key=f"item_name_{i}",
                              label_visibility="visible" if i == 0 else "collapsed",
                              placeholder=L["item_name"])
    with ic2:
        qty = st.number_input(L["qty"], min_value=1, value=1, key=f"item_qty_{i}",
                              label_visibility="visible" if i == 0 else "collapsed")
    with ic3:
        unit_price = st.number_input(L["unit_price"], min_value=0.0, value=0.0,
                                     step=1.0, key=f"item_price_{i}",
                                     label_visibility="visible" if i == 0 else "collapsed")
    with ic4:
        line_amount = qty * unit_price
        st.text_input(L["amount"], value=fmt_money(line_amount, sym),
                      disabled=True, key=f"item_amt_{i}",
                      label_visibility="visible" if i == 0 else "collapsed")
    with ic5:
        if i == 0:
            st.write("")  # spacer for alignment
        if i > 0:
            if st.button("✕", key=f"remove_{i}", help=L["remove_item"]):
                st.session_state.item_count -= 1
                # Clear keys for removed row to prevent ghost state
                for k in [f"item_name_{i}", f"item_qty_{i}", f"item_price_{i}", f"item_amt_{i}"]:
                    st.session_state.pop(k, None)
                st.rerun()

    items.append({"name": name, "qty": qty, "unit_price": unit_price, "amount": line_amount})
    subtotal += line_amount

if st.button(f"➕ {L['add_item']}"):
    st.session_state.item_count += 1
    st.rerun()

# --- Tax & Total ---
st.markdown("---")
t1, t2, t3 = st.columns(3)
with t1:
    tax_rate = st.number_input(L["tax_rate"], min_value=0.0, max_value=100.0,
                               value=10.0, step=0.5)
with t2:
    tax = subtotal * tax_rate / 100
    st.metric(L["tax"], fmt_money(tax, sym))
with t3:
    total = subtotal + tax
    st.metric(L["total"], fmt_money(total, sym))

st.caption(f"{L['subtotal']}: {fmt_money(subtotal, sym)}")

# --- Payment Info ---
st.subheader(L["payment_title"])
pc1, pc2, pc3 = st.columns(3)
with pc1:
    bank_name = st.text_input(L["bank_name"])
with pc2:
    account_no = st.text_input(L["account_no"])
with pc3:
    account_holder = st.text_input(L["account_holder"])

# --- Notes ---
st.subheader(L["notes_title"])
notes = st.text_area(L["notes_title"], placeholder=L["notes_placeholder"],
                     label_visibility="collapsed")

# --- Generate PDF ---
st.markdown("---")

if st.button(f"🖨️ {L['generate']}", type="primary", use_container_width=True):
    # Validate
    has_items = any(it["name"].strip() for it in items)
    if not from_company or not to_company or not has_items:
        st.error(L["fill_warning"])
    else:
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
            "items": [it for it in items if it["name"].strip()],
            "subtotal": subtotal,
            "tax_rate": tax_rate,
            "tax": tax,
            "total": total,
            "payment": {
                "bank": bank_name,
                "account_no": account_no,
                "holder": account_holder,
            },
            "notes": notes,
        }

        pdf_bytes = generate_pdf(invoice_data, lang_code, currency)

        st.success("✅")

        # Embed preview via iframe
        b64 = base64.b64encode(pdf_bytes).decode()
        pdf_display = (
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="800" type="application/pdf"></iframe>'
        )
        st.markdown(f"#### {L['preview']}")
        st.markdown(pdf_display, unsafe_allow_html=True)

        # Download button
        st.download_button(
            label=f"⬇️ {L['download']}",
            data=pdf_bytes,
            file_name=f"{invoice_no}.pdf",
            mime="application/pdf",
        )
