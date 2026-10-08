"""Example static-HTML spider (Kalibrr). Selectors are illustrative."""
import scrapy

from jobhunter_spiders.items import RawJobItem


class KalibrrSpider(scrapy.Spider):
    name = "kalibrr"
    source_name = "Kalibrr"
    start_urls = ["https://www.kalibrr.com/id-ID/job-board"]

    def parse(self, response):
        for card in response.css("div.job-brief, article.job"):
            yield RawJobItem(
                source=self.source_name,
                external_id=card.css("::attr(data-job-id)").get(default="").strip(),
                title=card.css("h3 a::text, .job-title::text").get(default="").strip(),
                company=card.css(".company-name::text").get(default="").strip(),
                location=card.css(".location::text").get(default="").strip(),
                salary=card.css(".salary::text").get(default="").strip(),
                employment_type="Full-time",
                description=card.css(".snippet::text").get(default="").strip(),
                skills=[],
                url=response.urljoin(card.css("h3 a::attr(href)").get(default="")),
                raw_html=card.get(),
            )
