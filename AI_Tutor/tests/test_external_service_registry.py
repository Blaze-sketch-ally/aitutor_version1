from services.external_service_registry import lookup


def test_lookup_finds_aws_certification():

    hit = lookup("aws certification")

    assert hit is not None
    assert hit["service_name"] == "AWS Certification"
    assert hit["url"].startswith("https://")


def test_lookup_returns_none_for_unknown_service():

    hit = lookup("completely made up service xyz123")

    assert hit is None


def test_lookup_returns_none_for_empty_query():

    assert lookup("") is None
    assert lookup("   ") is None
