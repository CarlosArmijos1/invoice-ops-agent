"""Fictional suppliers and products. Any resemblance to real companies is coincidental."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class VendorProfile:
    name: str
    printed_aliases: tuple[str, ...]  # how the name sometimes appears on invoices
    ruc_prefix: str  # province + body digits, see `make_ruc`
    ruc_kind: int
    email: str
    address: str
    products: tuple[tuple[str, Decimal], ...]


VENDORS: tuple[VendorProfile, ...] = (
    VendorProfile(
        name="Distribuidora Andina del Sur S.A.",
        printed_aliases=("DIST. ANDINA DEL SUR", "DISTRIBUIDORA ANDINA DEL SUR SA"),
        ruc_prefix="11765432",
        ruc_kind=9,
        email="facturacion@andinadelsur.example",
        address="Av. Universitaria 12-45 y Mercadillo, Loja",
        products=(
            ("Resma papel bond A4 75 g", Decimal("4.85")),
            ("Tóner compatible HP 26A", Decimal("38.90")),
            ("Archivador lomo ancho", Decimal("3.20")),
            ("Caja de esferos azules x12", Decimal("5.75")),
            ("Cuaderno universitario 100 hojas", Decimal("1.95")),
        ),
    ),
    VendorProfile(
        name="TecnoLoja Soluciones S.A.S.",
        printed_aliases=("TECNOLOJA SOLUCIONES", "TecnoLoja"),
        ruc_prefix="11223344",
        ruc_kind=9,
        email="ventas@tecnoloja.example",
        address="Calle Sucre 08-21 y Colón, Loja",
        products=(
            ('Laptop 14" Core i5 16 GB RAM', Decimal("689.00")),
            ('Monitor 24" IPS Full HD', Decimal("149.50")),
            ("Licencia antivirus anual", Decimal("32.00")),
            ("Switch 24 puertos gigabit", Decimal("214.90")),
            ("Soporte técnico (hora)", Decimal("25.00")),
        ),
    ),
    VendorProfile(
        name="Ferretería Zamora Hermanos Cía. Ltda.",
        printed_aliases=("FERRETERIA ZAMORA HNOS", "Ferretería Zamora"),
        ruc_prefix="19887766",
        ruc_kind=9,
        email="contabilidad@ferrezamora.example",
        address="Av. del Ejército y Segundo Cueva Celi, Zamora",
        products=(
            ("Cemento Portland saco 50 kg", Decimal("8.45")),
            ("Varilla corrugada 12 mm x 12 m", Decimal("11.30")),
            ("Pintura látex galón blanco", Decimal("17.80")),
            ("Tubo PVC 110 mm x 3 m", Decimal("9.60")),
            ("Juego de brocas para concreto", Decimal("22.40")),
        ),
    ),
    VendorProfile(
        name="Servicios de Limpieza Vilcabamba Cía. Ltda.",
        printed_aliases=("LIMPIEZA VILCABAMBA", "Serv. Limpieza Vilcabamba"),
        ruc_prefix="11554433",
        ruc_kind=9,
        email="admin@limpiezavilcabamba.example",
        address="Barrio Central, Vilcabamba, Loja",
        products=(
            ("Servicio de limpieza de oficinas (mes)", Decimal("420.00")),
            ("Desinfección de áreas comunes", Decimal("95.00")),
            ("Limpieza de vidrios en altura", Decimal("180.00")),
            ("Suministro de insumos de aseo", Decimal("64.30")),
        ),
    ),
    VendorProfile(
        name="Transportes Catamayo Express S.A.",
        printed_aliases=("TRANSPORTES CATAMAYO", "Catamayo Express"),
        ruc_prefix="11908070",
        ruc_kind=9,
        email="cobros@catamayoexpress.example",
        address="Vía a la Costa km 2, Catamayo",
        products=(
            ("Flete Loja - Guayaquil (tonelada)", Decimal("85.00")),
            ("Flete Loja - Quito (tonelada)", Decimal("110.00")),
            ("Seguro de carga", Decimal("18.50")),
            ("Estiba y desestiba", Decimal("35.00")),
        ),
    ),
    VendorProfile(
        name="Imprenta Saraguro Gráficas",
        printed_aliases=("IMPRENTA SARAGURO", "Saraguro Gráficas"),
        ruc_prefix="11345678",
        ruc_kind=1,
        email="imprenta.saraguro@example.com",
        address="Calle 10 de Marzo y Loja, Saraguro",
        products=(
            ("Volantes full color x1000", Decimal("45.00")),
            ("Tarjetas de presentación x500", Decimal("28.00")),
            ("Banner lona 2 x 1 m", Decimal("32.50")),
            ("Talonarios de recibos", Decimal("12.75")),
        ),
    ),
    VendorProfile(
        name="Café Podocarpus Catering S.A.",
        printed_aliases=("PODOCARPUS CATERING", "Café Podocarpus"),
        ruc_prefix="11112233",
        ruc_kind=9,
        email="eventos@podocarpuscatering.example",
        address="Av. Orillas del Zamora y Juan de Salinas, Loja",
        products=(
            ("Coffee break por persona", Decimal("4.50")),
            ("Almuerzo ejecutivo por persona", Decimal("7.80")),
            ("Servicio de meseros (hora)", Decimal("9.00")),
            ("Bebidas y agua (paquete)", Decimal("15.00")),
        ),
    ),
    VendorProfile(
        name="Constructora Malacatos Ingeniería S.A.",
        printed_aliases=("CONSTRUCTORA MALACATOS", "Malacatos Ingeniería"),
        ruc_prefix="11667788",
        ruc_kind=9,
        email="facturas@malacatosing.example",
        address="Vía Malacatos km 1, Loja",
        products=(
            ("Adecuación de oficinas (m2)", Decimal("68.00")),
            ("Instalación eléctrica (punto)", Decimal("42.00")),
            ("Mano de obra especializada (día)", Decimal("55.00")),
            ("Cielo raso de gypsum (m2)", Decimal("24.50")),
        ),
    ),
)

# Suppliers that appear on invoices but are NOT in the vendor master data.
UNKNOWN_VENDORS: tuple[VendorProfile, ...] = (
    VendorProfile(
        name="Comercializadora Nueva Era S.A.",
        printed_aliases=(),
        ruc_prefix="09123456",
        ruc_kind=9,
        email="ventas@nuevaera.example",
        address="Av. 9 de Octubre 1200, Guayaquil",
        products=(
            ("Kit de herramientas importado", Decimal("129.00")),
            ("Asesoría comercial (hora)", Decimal("60.00")),
        ),
    ),
    VendorProfile(
        name="Suministros Express del Pacífico",
        printed_aliases=(),
        ruc_prefix="13456789",
        ruc_kind=1,
        email="suministros.pacifico@example.com",
        address="Malecón y Calle 13, Manta",
        products=(
            ("Equipo de protección personal (kit)", Decimal("54.00")),
            ("Guantes de nitrilo caja x100", Decimal("11.90")),
        ),
    ),
)

BUYER = {
    "name": "Cooperativa Agroindustrial del Sur (demo)",
    "tax_id": "1191734929001",
    "address": "Av. 24 de Mayo y Azuay, Loja",
}
