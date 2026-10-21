import io
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from app.models.banking import Account, User
from app.core.security import format_iban


class PDFService:
    """Service de génération de documents bancaires officiels au format PDF."""

    @staticmethod
    def generate_rib_pdf(account: Account, user: User) -> bytes:
        """
        Génère un Relevé d'Identité Bancaire (RIB) officiel français au format PDF.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm
        )

        styles = getSampleStyleSheet()
        
        # Styles personnalisés
        header_title = ParagraphStyle(
            "HeaderTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a")
        )
        sub_title = ParagraphStyle(
            "SubTitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#64748b")
        )
        section_heading = ParagraphStyle(
            "SectionHeading",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#047857")
        )
        cell_bold = ParagraphStyle(
            "CellBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#1e293b")
        )
        cell_normal = ParagraphStyle(
            "CellNormal",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#334155")
        )
        iban_style = ParagraphStyle(
            "IBANStyle",
            parent=styles["Normal"],
            fontName="Courier-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#0f172a")
        )

        story = []

        # 1. En-tête de la Banque
        header_data = [
            [
                Paragraph("<b>NÉOBANQUE</b><br/><font color='#10b981'><b>CORE BANKING PORTAL</b></font>", header_title),
                Paragraph(
                    "<b>RELEVÉ D'IDENTITÉ BANCAIRE</b><br/>"
                    f"Édité le {datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')}<br/>"
                    "Réglementation ACPR / Banque de France",
                    sub_title
                )
            ]
        ]
        header_table = Table(header_data, colWidths=[9 * cm, 8 * cm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 15))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#10b981"), spaceAfter=15))

        # 2. Titulaire du Compte & Domiciliation
        holder_info = [
            [
                Paragraph("<b>TITULAIRE DU COMPTE</b>", section_heading),
                Paragraph("<b>DOMICILIATION BANCAIRE</b>", section_heading)
            ],
            [
                Paragraph(
                    f"<b>{user.full_name.upper()}</b><br/>"
                    f"Email : {user.email}<br/>"
                    f"Type de compte : {account.name} ({account.account_type.value})",
                    cell_normal
                ),
                Paragraph(
                    "<b>NÉOBANQUE FRANCE S.A.</b><br/>"
                    "Siège Social : 10 Rue de la Paix, 75002 Paris<br/>"
                    "Code Guichet Principal : 02050 Paris Opéra",
                    cell_normal
                )
            ]
        ]
        holder_table = Table(holder_info, colWidths=[9 * cm, 8 * cm])
        holder_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ]))
        story.append(holder_table)
        story.append(Spacer(1, 20))

        # 3. Coordonnées Nationales Françaises (RIB)
        story.append(Paragraph("IDENTIFIANTS BANCAIRES NATIONAUX (RIB)", section_heading))
        story.append(Spacer(1, 6))

        rib_data = [
            [
                Paragraph("<b>Code Banque</b>", cell_bold),
                Paragraph("<b>Code Guichet</b>", cell_bold),
                Paragraph("<b>N° de Compte</b>", cell_bold),
                Paragraph("<b>Clé RIB</b>", cell_bold)
            ],
            [
                Paragraph(account.bank_code, iban_style),
                Paragraph(account.branch_code, iban_style),
                Paragraph(account.account_number, iban_style),
                Paragraph(account.rib_key, iban_style)
            ]
        ]
        rib_table = Table(rib_data, colWidths=[3.5 * cm, 3.5 * cm, 7 * cm, 3 * cm])
        rib_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#334155")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(rib_table)
        story.append(Spacer(1, 20))

        # 4. Coordonnées Internationales SEPA (IBAN & BIC)
        story.append(Paragraph("IDENTIFIANTS INTERNATIONAUX SEPA (IBAN / BIC)", section_heading))
        story.append(Spacer(1, 6))

        formatted_iban = format_iban(account.iban)
        sepa_data = [
            [
                Paragraph("<b>Numéro IBAN (International Bank Account Number)</b>", cell_bold),
                Paragraph(f"<b>{formatted_iban}</b>", iban_style)
            ],
            [
                Paragraph("<b>Code BIC (Bank Identifier Code) / SWIFT</b>", cell_bold),
                Paragraph(f"<b>{account.bic}</b>", iban_style)
            ]
        ]
        sepa_table = Table(sepa_data, colWidths=[8 * cm, 9 * cm])
        sepa_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#f8fafc")),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(sepa_table)
        story.append(Spacer(1, 30))

        # 5. Mention légale de sécurité
        disclaimer_text = (
            "<b>MENTION DE SÉCURITÉ & AUTHENTICITÉ :</b><br/>"
            "Ce document certifie l'ouverture effective du compte bancaire mentionné ci-dessus. "
            "Il est destiné à être remis à vos débiteurs ou créanciers pour la mise en place de virements "
            "ou de prélèvements automatiques SEPA (Norme ISO 20022). "
            "Toute falsification de ce document constitue un délit pénal puni par l'article 441-1 du Code Pénal."
        )
        disclaimer = Paragraph(disclaimer_text, sub_title)
        story.append(disclaimer)

        doc.build(story)
        return buffer.getvalue()


pdf_service = PDFService()

