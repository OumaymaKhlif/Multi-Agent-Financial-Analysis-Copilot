import hmac, hashlib, os, time          # hmac/hashlib : signature ; os : lire le .env ; time : expiration

SECRET = os.getenv("APPROVAL_SECRET", "")  # clé secrète lue depuis l'environnement
TTL = 24 * 3600                            # durée de validité du lien : 24 h


def _sign(message: str) -> str:
    # Calcule la signature HMAC-SHA256 du message avec la clé secrète
    return hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()


def make_token(thread_id: str, action: str) -> str:
    exp = int(time.time()) + TTL                          # date d'expiration (timestamp)
    return f"{exp}.{_sign(f'{thread_id}:{action}:{exp}')}"  # token = expiration + signature


def verify_token(thread_id: str, action: str, token: str) -> bool:
    if not SECRET:                                        # sans clé configurée : tout refuser
        return False
    try:
        exp, sig = token.split(".")                       # séparer expiration et signature
        valid = hmac.compare_digest(sig, _sign(f"{thread_id}:{action}:{exp}"))  # signature correcte ?
        return valid and int(exp) > time.time()           # et lien non expiré ?
    except ValueError:                                    # token mal formé
        return False