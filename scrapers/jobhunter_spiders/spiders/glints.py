"""Example Playwright spider for a JS-rendered portal (Glints).

Selectors are illustrative — update them to the live site structure and honor
robots.txt / ToS before running.
"""
import scrapy

from jobhunter_spiders.items import RawJobItem


class GlintsSpider(scrapy.Spider):
    name = "glints"
    source_name = "Glints"
    uses_playwright = True
    start_urls = ["https://glints.com/id/opportunities/jobs/explore?country=ID"]

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(url, meta={"playwright": True}, callback=self.parse)

    def parse(self, response):
        for card in response.css("article.JobCard, [data-testid='job-card']"):
            yield RawJobItem(
                source=self.source_name,
                external_id=(card.css("::attr(data-id)").get()
                             or card.css("a::attr(href)").get() or "").strip(),
                title=card.css("h3::text, .job-title::text").get(default="").strip(),
                company=card.css(".company-name::text, [data-testid='company']::text").get(default="").strip(),
                location=card.css(".location::text").get(default="").strip(),
                salary=card.css(".salary::text").get(default="").strip(),
                employment_type="Full-time",
                description="",
                skills=[],
                url=response.urljoin(card.css("a::attr(href)").get(default="")),
                raw_html=card.get(),
            )
