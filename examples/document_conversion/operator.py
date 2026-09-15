"""Explicit operator actions; reads passwords privately, never puts them in shell history.

Run only against an account/environment you have reviewed and authorized.
"""

import argparse
import getpass
from typing import Any

import boto3
from botocore.exceptions import ClientError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass(
        "Permanent test-user password (14+ chars, mixed case/number/symbol): "
    )
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords differ")
    session: Any = boto3.Session(region_name=args.region)
    client = session.client("cognito-idp")
    try:
        client.admin_create_user(
            UserPoolId=args.pool,
            Username=args.email,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": args.email},
                {"Name": "email_verified", "Value": "true"},
            ],
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "UsernameExistsException":
            raise RuntimeError("TEST_USER_CREATE_FAILED") from None
    try:
        client.admin_set_user_password(
            UserPoolId=args.pool, Username=args.email, Password=password, Permanent=True
        )
    except ClientError:
        raise RuntimeError("TEST_PASSWORD_SETUP_FAILED") from None
    print("Approved test user is ready. Sign in through /documents.")


if __name__ == "__main__":
    main()
