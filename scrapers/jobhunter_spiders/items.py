import scrapy


class RawJobItem(scrapy.Item):
    """Raw, source-specific job record. The pipeline normalizes this into the
    canonical Job schema (see app/services/normalization.py)."""
    source = scrapy.Field()
    external_id = scrapy.Field()
    title = scrapy.Field()
    company = scrapy.Field()
    location = scrapy.Field()
    salary = scrapy.Field()
    employment_type = scrapy.Field()
    description = scrapy.Field()
    skills = scrapy.Field()
    url = scrapy.Field()
    raw_html = scrapy.Field()
