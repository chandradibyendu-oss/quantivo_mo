def sign_in(client, phone: str = "9876543210") -> dict:
    requested = client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert requested.status_code == 200, requested.text
    payload = requested.json()
    verified = client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": phone,
            "challenge_id": payload["challenge_id"],
            "otp": payload["dev_otp"],
            "device_label": "pytest",
        },
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
