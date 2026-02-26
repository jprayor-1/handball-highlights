from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict


@dataclass
class Timesheet:
    _id: str
    job_id: str
    clock_in: int  # Unix timestamp - this defines the “day” of the timesheet
    clock_out: int  # Unix timestamp


# Example data
example_timesheet = Timesheet(
    _id="ts_123", job_id="job_123", clock_in=1755446400, clock_out=1755451800
)


@dataclass
class DailyHoursSummary:
    day: int  # 1 = Monday, 7 = Sunday
    total_hours: float
    jobs_worked: list[str]  # unique list of job_ids


# Example function signature
def generate_daily_hours_summaries(
    timesheets: list[Timesheet],
) -> list[DailyHoursSummary]:
    """
    1) Accumulating all the time in timesheets
    2)

    weekday_num = date_obj.weekday()
    print(f"weekday() number: {weekday_num}")
    """
    accumulate_time = {}

    for time in timesheets:
        clock_in = datetime.fromtimestamp(time.clock_in)
        # Find Day of the week from time
        current_day = clock_in.weekday() + 1

        # Accumulate hours worked
        time_difference = (time.clock_out - time.clock_in) / 60
        time_difference_hours = time_difference / 60

        accumulate_time[current_day] = (
            accumulate_time.get(accumulate_time[current_day], []),
            time_difference_hours,
        )

        # Jobs_worked in the same day

        accumulate_time[current_day][0].append(time.job_id)

    # Convert to DailyHoursSummary
    daily_hour_summary = []
    for day, x in accumulate_time.items():
        daily_summary = DailyHoursSummary(day, total_hours=x[1], jobs_worked=x[0])
        daily_hour_summary.append(daily_summary)

    return daily_hour_summary


ex1 = Timesheet(
    _id="ts_123", job_id="job_123", clock_in=1755446400, clock_out=1755451800
)
ex2 = Timesheet(
    _id="ts_123", job_id="job_124", clock_in=1755446400, clock_out=1755451800
)

ex3 = Timesheet(
    _id="ts_123", job_id="job_125", clock_in=1755446400, clock_out=1755451800
)

ex4 = Timesheet(
    _id="ts_123", job_id="job_127", clock_in=1755446400, clock_out=1755482800
)


print(generate_daily_hours_summaries([ex1, ex2, ex3, ex4]))
