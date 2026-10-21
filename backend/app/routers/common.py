from ..models import Tenant
from ..schemas import TenantPublic
from ..storage import get_storage


def tenant_public(tenant: Tenant) -> TenantPublic:
    return TenantPublic(slug=tenant.slug, name=tenant.name, theme=tenant.theme, logo_url=get_storage().url(tenant.logo_path))
