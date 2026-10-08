"""Seed the database with realistic demo data.

Run:  python seed.py
Wipes and reseeds, so it is safe to run repeatedly.

Accounts created
----------------
demo@example.com      / demo12345       Job seeker — full profile and rich activity
andi@example.com      / password123   Job seeker — empty, to show the first-run states
hr@gojek.com          / password123   Employer — posted roles with live applicants
admin@jobhunter.local / admin123      Admin — ingestion health dashboard
"""
import random
import secrets
from datetime import datetime, timedelta, timezone

from app import create_app
from app.extensions import db
from app.models.employer import Employer, PostedJob, Resume
from app.models.job import Company, Job, JobSource, ScrapeRun, Source
from app.models.user import Application, JobAlert, SavedJob, User
from app.services.dedup import dedup_hash, find_matching_job
from app.services.normalization import normalize_job


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


SOURCES = [
    ("Glints", "https://glints.com", "playwright"),
    ("JobStreet", "https://jobstreet.co.id", "playwright"),
    ("Kalibrr", "https://kalibrr.com", "scrapy"),
    ("Dealls", "https://dealls.com", "playwright"),
    ("Tech in Asia", "https://techinasia.com/jobs", "scrapy"),
    ("Employer Portal", "/employer", "api"),
]

COMPANIES = [
    ("Gojek", "gojek.com", "On-demand services super-app serving millions across Southeast Asia."),
    ("Tokopedia", "tokopedia.com", "Indonesian e-commerce marketplace connecting buyers and sellers."),
    ("Traveloka", "traveloka.com", "Southeast Asian travel and lifestyle booking platform."),
    ("Bukalapak", "bukalapak.com", "E-commerce and digital commerce for Indonesian SMEs."),
    ("Blibli", "blibli.com", "Omni-commerce platform spanning retail and B2B."),
    ("DANA", "dana.id", "Digital wallet and financial services for everyday payments."),
    ("Ruangguru", "ruangguru.com", "Education technology platform for students and teachers."),
    ("Xendit", "xendit.co", "Payment infrastructure for businesses across Southeast Asia."),
    ("Ajaib", "ajaib.co.id", "Investment platform for first-time retail investors."),
    ("Bareksa", "bareksa.com", "Integrated online investment marketplace."),
    ("Kredivo", "kredivo.com", "Digital credit and buy-now-pay-later provider."),
    ("Sirclo", "sirclo.com", "Commerce enablement platform for brands and retailers."),
]

# (title, company, location, salary, employment_type, skills, description, source, days_ago)
JOBS = [
    # --- Engineering ---
    ("Senior Backend Engineer", "Gojek", "Jakarta", "IDR 25-40jt/bulan", "Full-time",
     ["Python", "Go", "PostgreSQL", "Kubernetes", "Microservices"],
     "Design and build high-throughput backend services powering payments and dispatch. "
     "Own APIs end to end, work with PostgreSQL and Kafka, deploy on Kubernetes. "
     "Strong Python or Go required.",
     "Glints", 1),
    # The same listing re-posted on a second portal. Demonstrates that cross-source
    # dedup collapses it into one canonical job with two source links. It has to be
    # the *same* title: dedup keys on canonical title + seniority, so a differently
    # scoped role (e.g. the intern posting below) is correctly kept separate.
    ("Senior Backend Engineer", "Gojek", "Jakarta", "IDR 25-40jt/bulan", "Full-time",
     ["Python", "Go", "PostgreSQL"],
     "Build reliable backend services for our core platform. Python, Go, PostgreSQL, "
     "microservices on Kubernetes.",
     "JobStreet", 1),
    ("Backend Engineer", "Tokopedia", "Jakarta", "IDR 15-25jt/bulan", "Full-time",
     ["Java", "Spring", "MySQL", "Kafka"],
     "Develop commerce backend services in Java/Spring. Work with MySQL, Kafka and "
     "distributed systems at scale.",
     "JobStreet", 2),
    ("Frontend Engineer", "Traveloka", "Jakarta", "IDR 18-28jt/bulan", "Full-time",
     ["React", "TypeScript", "Tailwind", "Next.js"],
     "Build delightful, fast web experiences with React, TypeScript and Next.js. "
     "Strong CSS/Tailwind and a love for clean UI.",
     "Glints", 1),
    ("Fullstack Engineer", "Xendit", "Remote", "IDR 20-35jt/bulan", "Full-time",
     ["Python", "Django", "React", "PostgreSQL"],
     "Work across the stack on payment products. Python/Django backend, React "
     "frontend, PostgreSQL. Fully remote within Indonesia.",
     "Dealls", 3),
    ("Software Engineer (Fresh Graduate)", "Blibli", "Jakarta", "IDR 8-12jt/bulan", "Full-time",
     ["JavaScript", "Node.js", "React"],
     "Kickstart your career building web features with JavaScript, Node.js and React. "
     "Structured mentorship provided.",
     "Tech in Asia", 2),
    ("Backend Engineer Intern", "Gojek", "Jakarta", "IDR 3-5jt/bulan", "Intern",
     ["Python", "SQL", "Git"],
     "Six-month internship on a backend team. Learn Python, SQL and Git while shipping "
     "real features with a mentor.",
     "Glints", 3),
    ("Mobile Engineer (Android)", "Gojek", "Jakarta", "IDR 20-33jt/bulan", "Full-time",
     ["Kotlin", "Android", "Jetpack Compose"],
     "Build features for our Android app used by millions. Kotlin, Jetpack Compose, "
     "and a focus on performance.",
     "Tech in Asia", 6),
    ("iOS Engineer", "Traveloka", "Jakarta", "IDR 20-32jt/bulan", "Full-time",
     ["Swift", "SwiftUI", "iOS"],
     "Develop our iOS app in Swift/SwiftUI. Ship polished features and care about app "
     "quality and testing.",
     "Glints", 7),
    ("DevOps Engineer", "Xendit", "Remote", "IDR 22-35jt/bulan", "Full-time",
     ["AWS", "Terraform", "Kubernetes", "Docker", "CI/CD"],
     "Own infrastructure and reliability. AWS, Terraform, Kubernetes, Docker and CI/CD "
     "pipelines. Remote-friendly.",
     "Dealls", 2),
    ("QA Engineer", "Bukalapak", "Bandung", "IDR 10-16jt/bulan", "Full-time",
     ["Selenium", "Cypress", "Test Automation", "API Testing"],
     "Design and automate test suites. Selenium/Cypress, API testing, and a "
     "quality-first mindset.",
     "JobStreet", 3),
    ("Security Engineer", "Xendit", "Remote", "IDR 25-40jt/bulan", "Full-time",
     ["Penetration Testing", "SIEM", "Cloud Security", "Python"],
     "Protect our platform and customers. Penetration testing, SIEM, cloud security and "
     "scripting in Python.",
     "Dealls", 5),
    ("Site Reliability Engineer", "Tokopedia", "Jakarta", "IDR 24-38jt/bulan", "Full-time",
     ["Kubernetes", "Prometheus", "Go", "Linux"],
     "Keep a high-traffic marketplace online. Kubernetes, Prometheus, Go and deep Linux "
     "fundamentals. On-call rotation shared across the team.",
     "Kalibrr", 4),
    ("Platform Engineer", "Sirclo", "Bandung", "IDR 18-30jt/bulan", "Full-time",
     ["Go", "Kubernetes", "Terraform", "PostgreSQL"],
     "Build the internal developer platform. Tooling, golden paths and self-service "
     "infrastructure for product teams.",
     "Glints", 6),
    ("Web Developer", "Ruangguru", "Yogyakarta", "IDR 9-14jt/bulan", "Contract",
     ["PHP", "Laravel", "MySQL", "JavaScript"],
     "Maintain and extend learning-platform web apps. PHP/Laravel, MySQL and vanilla "
     "JavaScript. Six-month contract with extension potential.",
     "JobStreet", 12),
    # --- Data ---
    ("Data Scientist", "Gojek", "Jakarta", "IDR 22-38jt/bulan", "Full-time",
     ["Python", "SQL", "Machine Learning", "TensorFlow", "Statistics"],
     "Build predictive models for pricing, fraud and demand forecasting. Python, SQL, "
     "machine learning and solid statistics.",
     "Kalibrr", 2),
    ("Data Analyst", "Tokopedia", "Jakarta", "IDR 12-18jt/bulan", "Full-time",
     ["SQL", "Python", "Tableau", "Excel"],
     "Turn data into decisions. Write SQL, build Tableau dashboards, and partner with "
     "product and marketing teams.",
     "JobStreet", 4),
    ("Data Engineer", "Traveloka", "Jakarta", "IDR 20-32jt/bulan", "Full-time",
     ["Python", "Spark", "Airflow", "BigQuery", "ETL"],
     "Build and maintain data pipelines with Spark and Airflow. Design warehousing in "
     "BigQuery and ensure data quality.",
     "Glints", 5),
    ("Machine Learning Engineer", "Tokopedia", "Jakarta", "IDR 25-42jt/bulan", "Full-time",
     ["Python", "PyTorch", "MLOps", "Deep Learning", "NLP"],
     "Productionize ML models for search and recommendations. Python, PyTorch, MLOps and "
     "NLP experience.",
     "Glints", 1),
    ("Business Intelligence Analyst", "Kredivo", "Jakarta", "IDR 13-20jt/bulan", "Full-time",
     ["SQL", "Looker", "dbt", "Analytics"],
     "Own reporting for the credit business. SQL, Looker and dbt, with a strong sense of "
     "what makes a metric trustworthy.",
     "Kalibrr", 7),
    # --- Design & Product ---
    ("Product Manager", "Gojek", "Jakarta", "IDR 25-40jt/bulan", "Full-time",
     ["Product Strategy", "Agile", "SQL", "Roadmapping"],
     "Own a product area end to end. Define strategy and roadmap, work with engineering "
     "and design, and drive outcomes.",
     "Kalibrr", 1),
    ("Product Designer", "Tokopedia", "Jakarta", "IDR 18-30jt/bulan", "Full-time",
     ["Figma", "UX Research", "Prototyping", "Design Systems"],
     "Design end-to-end flows for millions of users. Figma, UX research, prototyping and "
     "design systems.",
     "Glints", 4),
    ("UI/UX Designer", "Ruangguru", "Remote", "IDR 12-20jt/bulan", "Contract",
     ["Figma", "Adobe XD", "Wireframing"],
     "Create clear, accessible interfaces for education products. Figma/Adobe XD and "
     "strong wireframing skills.",
     "Dealls", 8),
    ("Graphic Designer", "Ajaib", "Jakarta", "IDR 7-11jt/bulan", "Full-time",
     ["Illustrator", "Photoshop", "Brand Design"],
     "Shape how a fast-growing investing brand looks. Illustrator, Photoshop and a strong "
     "eye for typography.",
     "JobStreet", 9),
    # --- Go-to-market ---
    ("Marketing Manager", "DANA", "Jakarta", "IDR 18-28jt/bulan", "Full-time",
     ["Digital Marketing", "SEO", "Google Ads", "Analytics"],
     "Lead growth campaigns across digital channels. SEO, Google Ads, analytics and "
     "lifecycle marketing.",
     "JobStreet", 5),
    ("Content Marketing Specialist", "Sirclo", "Remote", "IDR 8-13jt/bulan", "Full-time",
     ["Copywriting", "SEO", "Content Strategy"],
     "Write the stories that explain commerce software to growing brands. Copywriting, "
     "SEO and content strategy.",
     "Dealls", 6),
    ("Sales Executive", "Ajaib", "Jakarta", "IDR 8-15jt/bulan", "Full-time",
     ["B2B Sales", "CRM", "Negotiation"],
     "Drive B2B partnerships and revenue. CRM discipline, strong negotiation, and a "
     "hunter mentality.",
     "Kalibrr", 6),
    ("Account Manager", "Kredivo", "Surabaya", "IDR 9-15jt/bulan", "Full-time",
     ["Account Management", "CRM", "Relationship Building"],
     "Grow a portfolio of merchant partners across East Java. Account management, CRM "
     "hygiene and relationship building.",
     "JobStreet", 8),
    # --- Operations & corporate ---
    ("Finance Analyst", "Bareksa", "Jakarta", "IDR 10-16jt/bulan", "Full-time",
     ["Financial Modeling", "Excel", "Accounting"],
     "Support financial planning and analysis. Financial modeling, advanced Excel and "
     "accounting fundamentals.",
     "JobStreet", 9),
    ("HR Business Partner", "Traveloka", "Jakarta", "IDR 15-22jt/bulan", "Full-time",
     ["Recruitment", "HRIS", "Employee Relations"],
     "Partner with leaders on talent and people strategy. Recruitment, HRIS and employee "
     "relations.",
     "Kalibrr", 10),
    ("Talent Acquisition Specialist", "Sirclo", "Bandung", "IDR 8-13jt/bulan", "Full-time",
     ["Recruitment", "Sourcing", "Interviewing"],
     "Hire across engineering and go-to-market. Sourcing, structured interviewing and a "
     "genuinely candidate-friendly process.",
     "Dealls", 11),
    ("Operations Associate", "Blibli", "Surabaya", "IDR 6-9jt/bulan", "Full-time",
     ["Supply Chain", "Excel", "Process Improvement"],
     "Keep fulfilment running smoothly. Supply chain coordination, Excel modelling and a "
     "habit of improving processes.",
     "JobStreet", 7),
    ("Customer Support Specialist", "DANA", "Yogyakarta", "IDR 5-8jt/bulan", "Part-time",
     ["Communication", "Zendesk", "Problem Solving"],
     "Help users via chat and email. Great communication, Zendesk experience, and "
     "empathetic problem solving.",
     "JobStreet", 4),
    ("Customer Success Manager", "Xendit", "Denpasar", "IDR 12-18jt/bulan", "Full-time",
     ["Customer Success", "SaaS", "Onboarding"],
     "Help merchants get value from our payment stack. Onboarding, technical "
     "troubleshooting and clear communication.",
     "Glints", 10),
]

# (title, location, salary, employment_type, skills, description, days_ago, status)
EMPLOYER_POSTINGS = [
    ("Platform Engineer", "Jakarta", "IDR 28-45jt/bulan", "Full-time",
     ["Kubernetes", "Terraform", "Go", "Python", "AWS", "CI/CD"],
     "Own our internal developer platform. Build tooling around Kubernetes, Terraform and "
     "CI/CD. Python and Go. Improve developer experience and reliability.", 1, "active"),
    ("Senior Data Analyst", "Jakarta", "IDR 20-30jt/bulan", "Full-time",
     ["SQL", "Python", "Experimentation", "Looker"],
     "Sit with product teams and turn messy questions into clean analysis. Strong SQL, "
     "Python, and a solid grasp of experiment design.", 3, "active"),
    ("Customer Support Team Lead", "Yogyakarta", "IDR 12-18jt/bulan", "Full-time",
     ["Team Leadership", "Zendesk", "Coaching"],
     "Lead a support pod through our next stage of growth. Coaching, queue design and "
     "hands-on escalation handling.", 21, "closed"),
]


def seed() -> None:
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        # --- sources ---
        source_map = {}
        for name, url, engine in SOURCES:
            source = Source(name=name, base_url=url, engine=engine, enabled=True,
                            robots_status="n/a" if name == "Employer Portal" else "allowed",
                            tos_reviewed_at=utcnow())
            db.session.add(source)
            source_map[name] = source
        db.session.flush()

        # --- companies ---
        company_map = {}
        for name, website, description in COMPANIES:
            company = Company(name=name, slug=name.lower().replace(" ", "-"),
                              website=f"https://{website}", description=description)
            db.session.add(company)
            company_map[name] = company
        db.session.flush()

        # --- jobs (normalized + de-duplicated across sources) ---
        counts = {name: {"found": 0, "new": 0} for name in source_map}
        for (title, cname, location, salary, etype, skills, desc, sname, days) in JOBS:
            company = company_map[cname]
            norm = normalize_job({"title": title, "location": location, "salary": salary,
                                  "employment_type": etype, "description": desc,
                                  "skills": skills})
            existing, digest = find_matching_job(company.name, title, location)
            counts[sname]["found"] += 1
            if existing:
                existing.last_seen_at = utcnow()
                db.session.add(JobSource(
                    job_id=existing.id, source_id=source_map[sname].id,
                    external_id=f"{sname.lower()}-{existing.id}-{random.randint(1000, 9999)}",
                    url=f"https://example.com/{sname.lower()}/jobs/{existing.id}",
                    scraped_at=utcnow()))
            else:
                # Offset by hours rather than whole days, so the "Last 24h"
                # freshness filter returns a realistic handful of results.
                posted = utcnow() - timedelta(hours=days * 24 - random.randint(2, 7))
                job = Job(company_id=company.id, posted_at=posted, status="active", **norm)
                job.dedup_hash = digest
                db.session.add(job)
                db.session.flush()
                db.session.add(JobSource(
                    job_id=job.id, source_id=source_map[sname].id,
                    external_id=f"{sname.lower()}-{job.id}",
                    url=f"https://example.com/{sname.lower()}/jobs/{job.id}",
                    scraped_at=utcnow()))
                counts[sname]["new"] += 1
        db.session.flush()

        # A couple of stale listings so "active vs total" is not a flat number.
        for title, cname, days in [("Junior Backend Engineer", "Bukalapak", 48),
                                   ("Marketing Intern", "Ruangguru", 61)]:
            norm = normalize_job({
                "title": title, "location": "Jakarta", "salary": "IDR 5-8jt/bulan",
                "employment_type": "Intern", "skills": ["Python", "Excel"],
                "description": "Filled role kept for the archive."})
            job = Job(company_id=company_map[cname].id,
                      posted_at=utcnow() - timedelta(days=days), status="expired", **norm)
            job.dedup_hash = dedup_hash(cname, title, "Jakarta")
            db.session.add(job)
        db.session.flush()

        # --- ingestion history (varied outcomes, so the dashboard is not all green) ---
        outcomes = ["success", "success", "success", "partial", "failed"]
        for name, source in source_map.items():
            if name == "Employer Portal":
                continue
            for i in range(6):
                status = outcomes[(i + len(name)) % len(outcomes)]
                started = utcnow() - timedelta(hours=6 * i)
                run = ScrapeRun(
                    source_id=source.id,
                    started_at=started,
                    finished_at=started + timedelta(minutes=4),
                    status=status,
                    items_found=counts[name]["found"],
                    items_new=counts[name]["new"] if i == 0 else 0,
                    items_updated=random.randint(0, 3),
                    errors=0 if status == "success" else random.randint(1, 4),
                )
                if status == "failed":
                    run.error_detail = "Request blocked (HTTP 429) after 3 retries; backing off."
                elif status == "partial":
                    run.error_detail = "2 of 24 items skipped: missing company name."
                db.session.add(run)

        # --- users ---
        demo = User(email="demo@example.com", display_name="Rangga Wijaya",
                    default_location="Jakarta")
        demo.set_password("demo12345")

        andi = User(email="andi@example.com", display_name="Andi Pratama",
                    default_location="Bandung")
        andi.set_password("password123")

        admin = User(email="admin@jobhunter.local", display_name="Admin", is_admin=True)
        admin.set_password("admin123")

        employer_user = User(email="hr@gojek.com", display_name="Siti Rahmawati",
                             is_employer=True, default_location="Jakarta")
        employer_user.set_password("password123")

        db.session.add_all([demo, andi, admin, employer_user])
        db.session.flush()

        # --- demo resume: backend-leaning so AI matching has real signal ---
        db.session.add(Resume(
            user_id=demo.id, full_name="Rangga Wijaya",
            headline="Backend Engineer · Python, Flask & PostgreSQL",
            email="demo@example.com", phone="+62 812 3456 7890", location="Jakarta",
            summary=("Backend engineer with four years building and operating APIs in Python "
                     "(Flask, FastAPI) on PostgreSQL. I care about clear service boundaries, "
                     "honest tests and p95 latency. Comfortable owning a service from schema "
                     "design through to Kubernetes deploys and on-call."),
            skills=["Python", "Flask", "FastAPI", "PostgreSQL", "Docker", "Kubernetes",
                    "REST API", "SQL", "Git", "Redis", "CI/CD"],
            experiences=[
                {"role": "Backend Engineer", "company": "Fintech startup (Series B)",
                 "start": "2023", "end": "Present",
                 "description": ("Own the payments API surface serving 40k requests/minute. "
                                 "Cut p95 latency 40% by removing an N+1 query pattern and "
                                 "adding Redis caching. Run the service on Kubernetes with "
                                 "GitHub Actions CI/CD.")},
                {"role": "Junior Backend Developer", "company": "Software house",
                 "start": "2021", "end": "2023",
                 "description": ("Built REST APIs and internal tooling in Python for logistics "
                                 "clients. Wrote the team's first integration test suite and "
                                 "maintained MySQL databases.")},
            ],
            educations=[
                {"degree": "B.Sc. Computer Science",
                 "school": "Institut Teknologi Bandung", "year": "2021"},
            ],
            links={"linkedin": "https://linkedin.com/in/ranggawijaya",
                   "github": "https://github.com/ranggawijaya",
                   "portfolio": "https://rangga.dev"},
        ))

        # --- employer profile + postings ---
        employer = Employer(user_id=employer_user.id, company_name="Gojek",
                            company_id=company_map["Gojek"].id,
                            description=("On-demand services super-app serving millions across "
                                         "Southeast Asia."),
                            website="https://gojek.com")
        db.session.add(employer)
        db.session.flush()

        posted_jobs = []
        for (title, location, salary, etype, skills, desc, days, status) in EMPLOYER_POSTINGS:
            norm = normalize_job({"title": title, "location": location, "salary": salary,
                                  "employment_type": etype, "description": desc,
                                  "skills": skills})
            job = Job(company_id=company_map["Gojek"].id,
                      posted_at=utcnow() - timedelta(hours=days * 24 - random.randint(2, 7)),
                      status="active" if status == "active" else "expired", **norm)
            job.dedup_hash = dedup_hash("Gojek", title, location)
            db.session.add(job)
            db.session.flush()
            db.session.add(JobSource(
                job_id=job.id, source_id=source_map["Employer Portal"].id,
                external_id=f"posted-{job.id}", url=f"/jobs/{job.id}", scraped_at=utcnow()))
            posted = PostedJob(
                employer_id=employer.id, job_id=job.id, title=title,
                description=norm["description"], location=location,
                employment_type=norm["employment_type"], salary_min=norm["salary_min"],
                salary_max=norm["salary_max"], salary_currency=norm["salary_currency"],
                category=norm["category"], status=status)
            db.session.add(posted)
            posted_jobs.append(posted)
        db.session.flush()

        active_posted = [p for p in posted_jobs if p.status == "active"]

        # --- demo activity: a realistic pipeline, not an empty dashboard ---
        db.session.add(Application(
            user_id=demo.id, job_id=active_posted[0].job_id, posted_job_id=active_posted[0].id,
            status="interview",
            cover_note=("Hi Siti — I currently own a payments API and would love to work on "
                        "the developer platform side. Happy to walk through how we cut p95 "
                        "latency by 40%."),
            notes="Technical screen passed. System design round booked for Thursday.",
            created_at=utcnow() - timedelta(days=12),
            updated_at=utcnow() - timedelta(days=2)))
        db.session.add(Application(
            user_id=demo.id, job_id=active_posted[1].job_id, posted_job_id=active_posted[1].id,
            status="applied",
            cover_note="Applying for the analytics role — I work closely with our data team today.",
            created_at=utcnow() - timedelta(days=3),
            updated_at=utcnow() - timedelta(days=3)))

        # Self-tracked applications against external listings. Applications have a
        # unique (user, job) constraint, so exclude the two roles already applied to
        # through the employer flow above. Dates are staggered so the pipeline reads
        # like a real job search rather than a single bulk insert.
        already_applied = {active_posted[0].job_id, active_posted[1].job_id}
        external = (Job.query
                    .filter(Job.status == "active", Job.id.notin_(already_applied))
                    .order_by(Job.id).limit(4).all())
        tracker = [
            ("offer", "Offer received — negotiating start date and equity.", 31, 4),
            ("interview", "Second interview with the platform team next week.", 17, 6),
            ("rejected", "Rejected after the take-home. Feedback: wanted more Go.", 24, 19),
            ("other", "Recruiter reached out; waiting on the formal process.", 8, 8),
        ]
        for job, (status, note, created_days, updated_days) in zip(external, tracker):
            db.session.add(Application(
                user_id=demo.id, job_id=job.id, status=status, notes=note,
                created_at=utcnow() - timedelta(days=created_days),
                updated_at=utcnow() - timedelta(days=updated_days)))

        for job in Job.query.filter_by(status="active").limit(5).all():
            db.session.add(SavedJob(user_id=demo.id, job_id=job.id))

        db.session.add(JobAlert(
            user_id=demo.id, name="Backend roles in Jakarta",
            query={"q": "backend", "location": "Jakarta", "type": "", "category": "",
                   "salary_min": "", "remote": "", "freshness": ""},
            frequency="daily", unsubscribe_token=secrets.token_urlsafe(24), active=True,
            last_sent_at=utcnow() - timedelta(hours=9)))
        db.session.add(JobAlert(
            user_id=demo.id, name="Remote Python roles",
            query={"q": "python", "location": "", "type": "", "category": "",
                   "salary_min": "", "remote": "1", "freshness": "7"},
            frequency="weekly", unsubscribe_token=secrets.token_urlsafe(24), active=True))
        db.session.add(JobAlert(
            user_id=demo.id, name="Data roles (paused)",
            query={"q": "data", "location": "", "type": "", "category": "Data",
                   "salary_min": "", "remote": "", "freshness": ""},
            frequency="daily", unsubscribe_token=secrets.token_urlsafe(24), active=False))

        # --- applicants on the employer's live roles ---
        andi_resume = Resume(
            user_id=andi.id, full_name="Andi Pratama",
            headline="Fullstack Developer · JavaScript & Node.js",
            email="andi@example.com", phone="+62 813 2222 1111", location="Bandung",
            summary=("Fullstack developer with two years across React and Node.js. Comfortable "
                     "shipping end-to-end features and writing the tests to keep them honest."),
            skills=["JavaScript", "Node.js", "React", "PostgreSQL", "Git", "REST API"],
            experiences=[{"role": "Fullstack Developer", "company": "Digital agency",
                          "start": "2023", "end": "Present",
                          "description": "Delivered client web apps in React and Node.js."}],
            educations=[{"degree": "B.Sc. Information Systems", "school": "Universitas Padjadjaran",
                         "year": "2023"}],
            links={"linkedin": "https://linkedin.com/in/andipratama", "github": "", "portfolio": ""})
        db.session.add(andi_resume)

        db.session.add(Application(
            user_id=andi.id, job_id=active_posted[0].job_id, posted_job_id=active_posted[0].id,
            status="applied",
            cover_note="I would like to move from fullstack into platform work. Happy to learn Go."))
        db.session.add(Application(
            user_id=andi.id, job_id=active_posted[1].job_id, posted_job_id=active_posted[1].id,
            status="applied",
            cover_note="Strong SQL and reporting background from agency analytics work."))
        db.session.add(SavedJob(user_id=andi.id, job_id=active_posted[0].job_id))

        db.session.commit()

        active = Job.query.filter_by(status="active").count()
        print(f"Seeded {len(source_map)} sources, {len(company_map)} companies, "
              f"{Job.query.count()} jobs ({active} active after dedup), "
              f"{len(posted_jobs)} employer postings, 4 users, 2 resumes, "
              f"{Application.query.count()} applications.")
        print("\nDemo logins:")
        print("  Job seeker (full profile) : demo@example.com / demo12345")
        print("  Job seeker (empty state)  : andi@example.com / password123")
        print("  Employer                  : hr@gojek.com / password123")
        print("  Admin                     : admin@jobhunter.local / admin123")


if __name__ == "__main__":
    seed()
