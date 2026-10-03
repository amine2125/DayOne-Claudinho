"""Module de chiffrement local des données au repos (Zero-Knowledge On-Device Encryption).

Conforme à la contrainte du cahier des charges :
  "Le stockage local sur l'appareil doit être chiffré."

Assure le chiffrement transparent :
  1. Des images capturées stockées en local (AES-GCM / Fernet).
  2. Des données JSON sensibles persistées dans SQLite.
Aucun secret ni clé n'est transmis à un service cloud.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class LocalEncryptionManager:
    """Gestionnaire de chiffrement au repos pour le poste sage-femme / dispensaire."""

    def __init__(self, key_path: str | Path | None = None, secret_passphrase: str | None = None):
        if key_path is None:
            key_path = Path(__file__).resolve().parents[2] / ".device_secure_key"
        self.key_path = Path(key_path)
        self._fernet = self._init_cipher(secret_passphrase)

    def _init_cipher(self, passphrase: str | None) -> Fernet:
        """Initialise ou dérive la clé cryptographique locale."""
        if self.key_path.exists():
            key_bytes = self.key_path.read_bytes().strip()
            try:
                return Fernet(key_bytes)
            except Exception:
                pass

        # Génération ou dérivation d'une nouvelle clé locale
        if passphrase:
            salt = b"codeml_maternal_salt_2026"
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100_000,
            )
            derived = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(derived)
            return Fernet(derived)

        # Génération sécurisée d'une clé Fernet 256 bits
        new_key = Fernet.generate_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(new_key)
        return Fernet(new_key)

    def encrypt_bytes(self, data: bytes) -> bytes:
        """Chiffre un blob binaire (ex: photo de registre papier)."""
        if not data:
            return data
        return self._fernet.encrypt(data)

    def decrypt_bytes(self, cipher_data: bytes) -> bytes:
        """Déchiffre un blob binaire."""
        if not cipher_data:
            return cipher_data
        try:
            return self._fernet.decrypt(cipher_data)
        except Exception:
            # En cas de lecture d'une donnée historique déjà en clair
            return cipher_data

    def encrypt_text(self, text: str | None) -> str | None:
        """Chiffre une chaîne de caractères (ex: JSON extrait)."""
        if not text:
            return text
        enc = self.encrypt_bytes(text.encode("utf-8"))
        return enc.decode("latin1")

    def decrypt_text(self, cipher_text: str | None) -> str | None:
        """Déchiffre une chaîne de caractères."""
        if not cipher_text:
            return cipher_text
        try:
            raw = cipher_text.encode("latin1")
            dec = self.decrypt_bytes(raw)
            return dec.decode("utf-8")
        except Exception:
            return cipher_text


# Instance partagée pour l'application
crypto_manager = LocalEncryptionManager()
