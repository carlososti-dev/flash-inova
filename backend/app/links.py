from urllib.parse import urlencode

from .config import get_settings
from .models import Tenant


def frontend_link(tenant: Tenant | None, path: str, **params: str) -> str:
    """Link para uma tela do app, no endereço do hospital (subdomínio) ou da plataforma."""
    s = get_settings()
    if s.allow_tenant_override:
        # Desenvolvimento: tudo em localhost, hospital no parâmetro ?tenant=
        host = f"{s.base_domain}:{s.frontend_port}"
        if tenant:
            params = {**params, "tenant": tenant.slug}
    else:
        host = f"{tenant.slug}.{s.base_domain}" if tenant else s.base_domain
    query = f"?{urlencode(params)}" if params else ""
    return f"{s.public_scheme}://{host}{path}{query}"
