# Instrucciones para agentes

Proyecto final de DBA (PUJ 2026-30): techos solares en los 170 municipios PDET, con MongoDB.

- Estado y fechas de cada entrega: tabla "Entregas" en [`README.md`](README.md).
- Trabajo de cada entrega: `docs/deliveryN/`. Antes de trabajar en la Entrega 4, lee
  [`docs/delivery4/README.md`](docs/delivery4/README.md): fija Microsoft como fuente base y
  lista los municipios donde Google tiene cobertura insuficiente.
- Rutas, URIs y parámetros: [`config.yaml`](config.yaml). Contratos de datos:
  `scripts/entrega2_contracts.py` y `scripts/entrega3_contracts.py`.
- Pruebas: `python -m unittest discover -s tests`. Las pruebas de MongoDB necesitan
  `docker compose up -d` y `MONGO_URI=mongodb://admin:admin123@localhost:27017/`.
- Cada integrante debe tener commits propios en cada entrega. No reemplaces el trabajo de otro
  integrante sin acordarlo con el equipo.
