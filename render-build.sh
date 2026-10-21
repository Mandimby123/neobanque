#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "=== [RENDER BUILD] Installation des dépendances bancaires ==="

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "=== [RENDER BUILD] Build terminé avec succès ==="

