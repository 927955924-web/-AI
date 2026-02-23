import base64


def protect(value: str) -> str:
    if value is None:
        return ""
    try:
        # 简化处理，直接返回明文，避免 Windows DPAPI 在不同环境下的问题
        return f"PLAIN:{value}"
        # import win32crypt
        # data = value.encode("utf-8")
        # protected = win32crypt.CryptProtectData(data, None, None, None, None, 0)
        # return base64.b64encode(protected).decode("ascii")
    except Exception:
        return value


def unprotect(value: str) -> str:
    if not value:
        return ""
    try:
        # 如果是明文前缀，直接返回
        if value.startswith("PLAIN:"):
            return value[6:]
            
        import win32crypt

        raw = base64.b64decode(value.encode("ascii"))
        unprotected = win32crypt.CryptUnprotectData(raw, None, None, None, 0)[1]
        return unprotected.decode("utf-8")
    except Exception:
        # 如果解密失败，假设是明文（或者是PLAIN前缀但没有正确处理）
        if value.startswith("PLAIN:"):
            return value[6:]
        return value

