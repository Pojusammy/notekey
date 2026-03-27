#!/usr/bin/env bash
# Render build script for the NoteKey backend
set -o errexit

pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt
