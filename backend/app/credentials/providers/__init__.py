"""Generic auth providers package."""
from .base import AuthProvider
from .basic import BasicAuthProvider
from .bearer import BearerAuthProvider
from .header import HeaderAuthProvider
from .query import QueryAuthProvider
from .digest import DigestAuthProvider
from .custom import CustomAuthProvider
from .oauth1 import OAuth1Provider
from .oauth2 import OAuth2Provider
from .none import NoneAuthProvider
from .api_key import ApiKeyAuthProvider
from .pat import PatAuthProvider
from .jwt import JwtAuthProvider
from .service_account import ServiceAccountAuthProvider
from .aws_iam import AwsIamAuthProvider
from .aws_assume_role import AwsAssumeRoleAuthProvider

__all__ = [
    "AuthProvider",
    "BasicAuthProvider",
    "BearerAuthProvider",
    "HeaderAuthProvider",
    "QueryAuthProvider",
    "DigestAuthProvider",
    "CustomAuthProvider",
    "OAuth1Provider",
    "OAuth2Provider",
    "NoneAuthProvider",
    "ApiKeyAuthProvider",
    "PatAuthProvider",
    "JwtAuthProvider",
    "ServiceAccountAuthProvider",
    "AwsIamAuthProvider",
    "AwsAssumeRoleAuthProvider",
]
