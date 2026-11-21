"""ثبت مدل‌های همه ماژول‌ها برای Alembic و create_all."""
from app.modules.integrations import models as integrations_models  # noqa: F401
from app.modules.persons import models as persons_models  # noqa: F401
from app.modules.organizations import models as organizations_models  # noqa: F401
from app.modules.references import models as references_models  # noqa: F401
from app.modules.identities import models as identities_models  # noqa: F401
from app.modules.ownership import models as ownership_models  # noqa: F401
from app.modules.change_requests import models as change_requests_models  # noqa: F401
from app.modules.data_quality import models as data_quality_models  # noqa: F401
from app.modules.synchronization import models as synchronization_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401

from app.common.db import Base  # noqa: F401
from app.modules.masterdata import models as masterdata_models  # noqa: F401
