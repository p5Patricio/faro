"""Parse a CFDI 4.0 invoice (SAT XML) into the facts Faro stores, using only
the standard library. Pure: no I/O. Informational: flags are hints for the
user and their accountant, never a deduction decision.

Sources and verification status: ``docs/sat/cfdi-e-importadores.md``. The
``c_UsoCFDI`` labels D01 and D10 were read on SAT pages; D02-D09 come from
secondary sources (``status: reportado``). ``FormaPago`` "01" (cash) is the
well-known catalog value but was not re-read on ``catCFDI.xls``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree

CFDI_NS = "http://www.sat.gob.mx/cfd/4"
TFD_NS = "http://www.sat.gob.mx/TimbreFiscalDigital"
MAX_XML_BYTES = 2_000_000

CASH_PAYMENT_FORM = "01"

PERSONAL_DEDUCTION_USES: dict[str, tuple[str, str]] = {
    "D01": ("Honorarios médicos, dentales y gastos hospitalarios", "verificado"),
    "D02": ("Gastos médicos por incapacidad o discapacidad", "reportado"),
    "D03": ("Gastos funerales", "reportado"),
    "D04": ("Donativos", "reportado"),
    "D05": ("Intereses reales pagados por créditos hipotecarios (casa habitación)", "reportado"),
    "D06": ("Aportaciones voluntarias al SAR", "reportado"),
    "D07": ("Primas por seguros de gastos médicos", "reportado"),
    "D08": ("Gastos de transportación escolar obligatoria", "reportado"),
    "D09": ("Depósitos en cuentas para el ahorro, primas con base en planes de pensiones", "reportado"),
    "D10": ("Pagos por servicios educativos (colegiaturas)", "verificado"),
}


class CfdiError(ValueError):
    """The document is not a stamped CFDI 4.0 this parser can read."""


def _cents(value: str | None, field: str) -> int:
    try:
        amount = Decimal(value or "")
    except InvalidOperation:
        raise CfdiError(f"El atributo {field} no es un monto válido.") from None
    if not amount.is_finite():
        raise CfdiError(f"El atributo {field} no es un monto válido.")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_cfdi(xml: bytes) -> dict[str, Any]:
    if len(xml) > MAX_XML_BYTES:
        raise CfdiError("El archivo es demasiado grande para ser un CFDI.")
    # A CFDI never declares a DTD; refusing one rules out entity-expansion tricks.
    if b"<!DOCTYPE" in xml.upper():
        raise CfdiError("El XML declara un DOCTYPE; un CFDI no lo usa.")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise CfdiError("El archivo no es XML válido.") from None
    if root.tag != f"{{{CFDI_NS}}}Comprobante":
        raise CfdiError("Solo se admiten CFDI versión 4.0 (cfdi:Comprobante).")

    issuer = root.find(f"{{{CFDI_NS}}}Emisor")
    receiver = root.find(f"{{{CFDI_NS}}}Receptor")
    stamp = root.find(f"{{{CFDI_NS}}}Complemento/{{{TFD_NS}}}TimbreFiscalDigital")
    if issuer is None or receiver is None:
        raise CfdiError("Faltan los nodos Emisor o Receptor.")
    if stamp is None or not stamp.get("UUID"):
        raise CfdiError("El CFDI no está timbrado (falta el TimbreFiscalDigital con su UUID).")

    exchange_rate = root.get("TipoCambio")
    concepts = [
        {
            "clave_prod_serv": concept.get("ClaveProdServ"),
            "descripcion": concept.get("Descripcion"),
            "importe_cents": _cents(concept.get("Importe"), "Importe"),
        }
        for concept in root.iterfind(f"{{{CFDI_NS}}}Conceptos/{{{CFDI_NS}}}Concepto")
    ]
    return {
        "uuid": stamp.get("UUID").lower(),
        "version": root.get("Version") or "4.0",
        "issued_at": root.get("Fecha"),
        "invoice_type": root.get("TipoDeComprobante"),
        "issuer_rfc": issuer.get("Rfc"),
        "issuer_name": issuer.get("Nombre"),
        "receiver_rfc": receiver.get("Rfc"),
        "uso_cfdi": receiver.get("UsoCFDI"),
        "payment_form": root.get("FormaPago"),
        "payment_method": root.get("MetodoPago"),
        "currency": (root.get("Moneda") or "MXN").upper(),
        "exchange_rate": exchange_rate,
        "subtotal_cents": _cents(root.get("SubTotal"), "SubTotal"),
        "total_cents": _cents(root.get("Total"), "Total"),
        "concepts": concepts,
    }


def deduction_hints(document: dict[str, Any]) -> dict[str, Any]:
    """What the user should look at, never a verdict: whether the use is a
    personal-deduction use (D01-D10) and whether the invoice says cash."""
    use = (document.get("uso_cfdi") or "").upper()
    label, status = PERSONAL_DEDUCTION_USES.get(use, (None, None))
    return {
        "personal_deduction_use": label is not None,
        "use_label": label,
        "use_label_status": status,
        "paid_in_cash": document.get("payment_form") == CASH_PAYMENT_FORM,
    }
