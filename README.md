# Receiptr

Registrá los gastos de tu familia mandando una foto del ticket por WhatsApp. El bot extrae los datos automáticamente y los guarda en una planilla de Google compartida.

---

## ¿Cómo funciona?

### 1. Mandá una foto del ticket

Enviá una foto del ticket al número de WhatsApp del bot.

El bot te responde con un resumen de lo que encontró:

```
Esto es lo que encontré:
  Comercio: COTO
  Fecha: 07/03/2026
  Total: $ 23.686,33
  Categoría: Supermercado
  Items: Arroz, Queso, Banana, Zanahoria...

Respondé SI para guardar, NO para cancelar, o corregí un dato:
  corregir total 52.10
  corregir comercio Lidl
```

---

### 2. Confirmá o corregí

Tenés tres opciones:

| Respuesta | Qué hace |
|-----------|----------|
| `SI` | Guarda el ticket en la planilla |
| `NO` | Cancela, no guarda nada |
| `corregir <campo> <valor>` | Corrige un dato y muestra el resumen actualizado |

**Campos que podés corregir:**

| Comando | Ejemplo |
|---------|---------|
| `corregir total` | `corregir total 15000.50` |
| `corregir comercio` | `corregir comercio Carrefour` |
| `corregir fecha` | `corregir fecha 05/03/2026` |
| `corregir categoria` | `corregir categoria Farmacia` |
| `corregir items` | `corregir items leche, pan, huevos` |

---

### 3. Guardado y resumen

Si respondés `SI`, el bot confirma y te muestra el resumen del mes:

```
Listo, guardado en la planilla!

*Resumen:*
Marzo 2026  |  Tienda: COTO  |  Total: $ 23.686,33  |  1 ticket
```

---

## La planilla

Los datos se guardan en Google Sheets con dos pestañas:

- **Tickets** — un registro por cada ticket escaneado
- **Resumen** — totales por mes, actualizados automáticamente

---

## Para unirse al bot (primera vez)

1. Enviá el código de acceso al número de WhatsApp del bot:
   ```
   join <código>
   ```
2. Esperá la confirmación de WhatsApp
3. A partir de ahí podés mandar fotos de tickets

> El código de acceso lo tenés que pedir al administrador de la familia.
