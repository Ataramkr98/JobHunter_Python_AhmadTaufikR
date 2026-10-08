"""Import every model so all tables register on db.metadata before db.create_all()."""
from app.models.job import Source, Company, Job, JobSource, ScrapeRun
from app.models.user import User, SavedJob, JobAlert, Application
from app.models.employer import Employer, PostedJob, Resume

__all__ = [
    "Source", "Company", "Job", "JobSource", "ScrapeRun",
    "User", "SavedJob", "JobAlert", "Application",
    "Employer", "PostedJob", "Resume",
]
