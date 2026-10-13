"""Parse a CFDI de Retenciones e información de pagos 2.0 (a broker's annual
constancia) and reconcile it against the investment ledger, using only the
standard library. Pure: no I/O. Informational: a difference is a hint to ask
the broker or the accountant, never a tax figure or a verdict.

Three complements are understood: ``intereses`` (CveRetenc 16),
``dividendos`` (14) and ``enajenaciondeacciones`` (19). Any complement amount
that is missing counts as zero. Money is integer cents, half-up from the XML's
decimal string; a ``float`` never touches an amount.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree

RET_NS = "http://www.sat.gob.mx/esquemas/retencionpago/2"
INTEREST_NS = "http://www.sat.gob.mx/esquemas/retencionpago/1/intereses"
DIVIDEND_NS = "http://www.sat.gob.mx/esquemas/retencionpago/1/dividendos"
SALE_NS = "http://www.sat.gob.mx/esquemas/retencionpago/1/enajenaciondeacciones"
TFD_NS = "http://www.sat.gob.mx/TimbreFiscalDigital"
MAX_XML_BYTES = 2_000_000

# The SAT's generic national RFC: a constancia issued to it is not linked to the user's RFC.
GENERIC_RFC = "XAXX010101000"

CONCEPT_BY_CVE = {"16": "intereses", "14": "dividendos", "19": "enajenacion"}


class RetencionesError(ValueError):
    """The document is not a stamped CFDI de Retenciones 2.0 this parser can read."""


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _cents(attributes: Mapping[str, str], field: str) -> int:
    try:
        amount = Decimal(attributes.get(field) or "0")
    except InvalidOperation:
        raise RetencionesError(f"El atributo {field} no es un monto válido.") from None
    if not amount.is_finite():
        raise RetencionesError(f"El atributo {field} no es un monto válido.")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _int(attributes: Mapping[str, str], field: str) -> int:
    try:
        return int(attributes.get(field) or "")
    except ValueError:
        raise RetencionesError(f"El atributo {field} no es válido.") from None


def _attributes(parent: ElementTree.Element, *path: tuple[str, str]) -> Mapping[str, str]:
    """Attributes of the element at ``path`` (namespace, name pairs), or ``{}`` when it is absent."""
    found = parent.find("/".join(_tag(namespace, name) for namespace, name in path))
    return found.attrib if found is not None else {}


def _complement(concept: str, complemento: ElementTree.Element) -> dict[str, Any]:
    if concept == "intereses":
        a = _attributes(complemento, (INTEREST_NS, "Intereses"))
        return {
            "nominal_cents": _cents(a, "MontIntNominal"),
            "real_cents": _cents(a, "MontIntReal"),
            "loss_cents": _cents(a, "Perdida"),
        }
    if concept == "dividendos":
        a = _attributes(complemento, (DIVIDEND_NS, "Dividendos"), (DIVIDEND_NS, "DividOUtil"))
        return {
            "dividend_type": a.get("CveTipDivOUtil"),
            "accumulable_mx_cents": _cents(a, "MontDivAcumNal"),
            "accumulable_foreign_cents": _cents(a, "MontDivAcumExt"),
            "isr_creditable_mx_cents": _cents(a, "MontISRAcredRetMexico"),
            "isr_creditable_foreign_cents": _cents(a, "MontISRAcredRetExtranjero"),
            "isr_creditable_nal_cents": _cents(a, "MontISRAcredNal"),
            "withheld_foreign_div_ext_cents": _cents(a, "MontRetExtDivExt"),
        }
    if concept == "enajenacion":
        a = _attributes(complemento, (SALE_NS, "EnajenaciondeAcciones"))
        return {
            "contract": a.get("ContratoIntermediacion"),
            "gain_cents": _cents(a, "Ganancia"),
            "loss_cents": _cents(a, "Perdida"),
        }
    return {}


def parse_retenciones(xml: bytes) -> dict[str, Any]:
    if len(xml) > MAX_XML_BYTES:
        raise RetencionesError("El archivo es demasiado grande para ser una constancia de retenciones.")
    # A constancia never declares a DTD; refusing one rules out entity-expansion tricks.
    if b"<!DOCTYPE" in xml.upper():
        raise RetencionesError("El XML declara un DOCTYPE; una constancia de retenciones no lo usa.")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise RetencionesError("El archivo no es XML válido.") from None
    if root.tag != _tag(RET_NS, "Retenciones") or root.get("Version") != "2.0":
        raise RetencionesError("Solo se admiten constancias de retenciones versión 2.0 (retenciones:Retenciones).")

    issuer = root.find(_tag(RET_NS, "Emisor"))
    receiver = root.find(_tag(RET_NS, "Receptor"))
    period = root.find(_tag(RET_NS, "Periodo"))
    totals = root.find(_tag(RET_NS, "Totales"))
    complemento = root.find(_tag(RET_NS, "Complemento"))
    if issuer is None or receiver is None or period is None or totals is None:
        raise RetencionesError("Faltan los nodos Emisor, Receptor, Periodo o Totales.")
    stamp = complemento.find(_tag(TFD_NS, "TimbreFiscalDigital")) if complemento is not None else None
    if stamp is None or not stamp.get("UUID"):
        raise RetencionesError("La constancia no está timbrada (falta el TimbreFiscalDigital con su UUID).")

    cve_retenc = root.get("CveRetenc") or ""
    concept = CONCEPT_BY_CVE.get(cve_retenc, "otro")
    receiver_rfc = _attributes(receiver, (RET_NS, "Nacional")).get("RfcR")
    return {
        "uuid": stamp.get("UUID").lower(),
        "folio": root.get("FolioInt"),
        "issued_at": root.get("FechaExp"),
        "year": _int(period.attrib, "Ejercicio"),
        "month_start": _int(period.attrib, "MesIni"),
        "month_end": _int(period.attrib, "MesFin"),
        "cve_retenc": cve_retenc,
        "concept": concept,
        "emitter_rfc": issuer.get("RfcE"),
        "emitter_name": issuer.get("NomDenRazSocE"),
        "receiver_rfc": receiver_rfc,
        "receiver_nationality": receiver.get("NacionalidadR"),
        "receiver_is_generic": receiver_rfc == GENERIC_RFC,
        "operation_cents": _cents(totals.attrib, "MontoTotOperacion"),
        "taxable_cents": _cents(totals.attrib, "MontoTotGrav"),
        "exempt_cents": _cents(totals.attrib, "MontoTotExent"),
        "withheld_cents": _cents(totals.attrib, "MontoTotRet"),
        "withholdings": [
            {
                "base_cents": _cents(node.attrib, "BaseRet"),
                "tax": node.get("ImpuestoRet"),
                "amount_cents": _cents(node.attrib, "MontoRet"),
                "payment_type": node.get("TipoPagoRet"),
            }
            for node in totals.iterfind(_tag(RET_NS, "ImpRetenidos"))
        ],
        "complement": _complement(concept, complemento),
    }


def reconcile_year(
    documents: list[dict[str, Any]], worksheet: Mapping[str, Any], *, tolerance_cents: int = 100
) -> list[dict[str, Any]]:
    """Constancia figures against the ledger's yearly worksheet (all accounts), per concept.

    ``status``: ``coincide`` when the gap is within ``tolerance_cents``, ``difiere``
    when it is not, ``sin_libro`` when the year has constancias but no ledger
    entries of that kind, ``sin_constancia`` for the reverse. A concept with
    neither side is left out.
    """
    by_concept = {
        concept: [d for d in documents if d["concept"] == concept] for concept in CONCEPT_BY_CVE.values()
    }

    def total(concept: str, key: str) -> int:
        return sum(d["complement"].get(key, 0) for d in by_concept[concept])

    interest_withheld = sum(d["withheld_cents"] for d in by_concept["intereses"])
    sale_net = total("enajenacion", "gain_cents") - total("enajenacion", "loss_cents")
    # The ledger books the dividend actually paid (MontoTotOperacion). The complement's
    # MontDivAcumNal is grossed up (x 1.4286, LISR art. 140), so it would never match.
    dividends = sum(d["operation_cents"] for d in by_concept["dividendos"])
    dividends_accumulable = total("dividendos", "accumulable_mx_cents") + total("dividendos", "accumulable_foreign_cents")
    checks = (
        # (row concept, documents' concept, constancia cents, ledger kinds, ledger field)
        ("interest", "intereses", total("intereses", "nominal_cents"), ("interest",), "amount_mxn_cents"),
        ("interest_withheld", "intereses", interest_withheld, ("interest",), "tax_withheld_mxn_cents"),
        ("dividends", "dividendos", dividends, ("dividend", "fibra_distribution"), "amount_mxn_cents"),
        ("sale", "enajenacion", sale_net, ("sale_gain",), "amount_mxn_cents"),
    )
    rows = []
    for concept, document_concept, constancia, kinds, field in checks:
        has_documents = bool(by_concept[document_concept])
        entries = [item for item in worksheet["summary"] if item["concept"] in kinds]
        if not has_documents and not entries:
            continue
        ledger = sum(item[field] for item in entries)
        difference = constancia - ledger
        if not entries:
            status = "sin_libro"
        elif not has_documents:
            status = "sin_constancia"
        else:
            status = "coincide" if abs(difference) <= tolerance_cents else "difiere"
        row = {
            "concept": concept,
            "constancia_cents": constancia,
            "ledger_cents": ledger,
            "difference_cents": difference,
            "status": status,
        }
        if concept == "interest":
            row["constancia_real_cents"] = total("intereses", "real_cents")
            row["constancia_loss_cents"] = total("intereses", "loss_cents")
        if concept == "dividends":
            row["constancia_accumulable_cents"] = dividends_accumulable
        rows.append(row)
    return rows
