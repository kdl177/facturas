# Facturas y presupuestos · SIMBAI Lab

Facturas y presupuestos para autónomos y pequeñas empresas, sin cuentas, sin suscripción y sin internet. Funciona en tu ordenador y los datos se quedan en un archivo tuyo.

- **Numeración correlativa** por año: `F2026-0001`, `P2026-0001`. El número se asigna al emitir.
- **Lo emitido no se toca.** Una factura emitida no se puede modificar ni borrar; las fechas tienen que ir en el orden de la numeración. Los datos de emisor y cliente se guardan con la factura.
- **IVA por línea** (21, 10, 4 y 0 %) con su desglose, y **retención de IRPF** (7, 15 o 19 %).
- **Presupuesto a factura** con un clic, y estados: pendiente, cobrada, aceptado, rechazado.
- **PDF** desde el propio navegador: Imprimir y "Guardar como PDF".
- **Pendiente de cobro** de un vistazo.

> No está adaptado a VeriFactu. Cuando la obligación te alcance, necesitarás un software de facturación homologado. Para correcciones de facturas emitidas hay que emitir una rectificativa, que esta versión no hace.

## Instalar (Windows)

1. Python 3.11 o superior. No hace falta nada más.
2. Doble clic en `iniciar.bat`: se abre en `http://127.0.0.1:8414`.
3. Rellena **Mis datos**, añade un cliente y crea la primera factura.

## Tus datos

Todo se guarda en `facturas.db`, en la carpeta del programa. Haz copia de ese archivo: es tu registro de facturas.

| Variable | Por defecto |
|---|---|
| `FACTURAS_PUERTO` | `8414` |
| `FACTURAS_BD` | `facturas.db` junto al programa |
