"""The ten Kip modules — organised around what international students actually ask."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    emoji: str
    tagline: str
    examples: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


MODULES: list[Module] = [
    Module("arrive", "Just Landed", "🛬", "Your first 30 days in Australia, step by step",
           ["What should I do in my first week in Australia?",
            "What documents do I need to set up my life here?"],
           ["studyaustralia.gov.au", "homeaffairs.gov.au"]),
    Module("visa", "Visas & Work Rights", "🛂", "Student 500, Graduate 485, and your work-hour limits",
           ["How many hours can I work on a student visa?",
            "How do I apply for the 485 visa after graduation?",
            "How do I check my visa conditions?"],
           ["immi.homeaffairs.gov.au", "vevo.homeaffairs.gov.au"]),
    Module("tax", "TFN, Tax & Super", "🧾", "Get your Tax File Number, understand tax and superannuation",
           ["How do I apply for a TFN?",
            "What happens if I work without a TFN?",
            "Can I claim my super when I leave Australia?"],
           ["ato.gov.au", "my.gov.au"]),
    Module("work", "Jobs & Pay Rights", "💼", "Minimum wage, payslips, and what to do if you are underpaid",
           ["What is the minimum wage in Australia?",
            "My employer pays me cash below minimum wage — what can I do?"],
           ["fairwork.gov.au"]),
    Module("housing", "Housing & Rentals", "🏠", "Find listings on trusted sites, understand bond and your rights",
           ["Two bedroom house near Acacia Ridge 4110 Brisbane",
            "How much bond do I pay and how do I get it back?",
            "What do I need to apply for a rental?"],
           ["realestate.com.au", "domain.com.au", "flatmates.com.au"]),
    Module("health", "OSHC & Healthcare", "🏥", "Your health cover, seeing a doctor, and emergency numbers",
           ["What does my OSHC actually cover?",
            "Am I eligible for Medicare as a student?"],
           ["servicesaustralia.gov.au", "privatehealth.gov.au", "healthdirect.gov.au"]),
    Module("money", "Banking & Money", "🏦", "Open a bank account, send money home, avoid bad exchange rates",
           ["Which bank account is best for students?",
            "Can I open a bank account before I arrive?"],
           ["moneysmart.gov.au"]),
    Module("transport", "Getting Around", "🚋", "Transport cards, student concessions, city by city",
           ["How do I get a student discount on public transport in Brisbane?"],
           ["translink.com.au", "transportnsw.info", "ptv.vic.gov.au"]),
    Module("study", "Student Life & Discounts", "🎓", "UNiDAYS, cheap groceries, making the most of student life",
           ["What student discounts can I get in Australia?",
            "How much should I budget for groceries each week?"],
           ["unidays.com", "studentbeans.com", "studyaustralia.gov.au"]),
    Module("safety", "Safety, Scams & Emergencies", "🛡️", "Emergency numbers, scams targeting students, mental health support",
           ["Someone called saying my visa will be cancelled unless I pay — is this a scam?",
            "Where can I get mental health support as a student?"],
           ["scamwatch.gov.au", "healthdirect.gov.au", "lifeline.org.au"]),
]

MODULE_IDS = frozenset(m.id for m in MODULES)
