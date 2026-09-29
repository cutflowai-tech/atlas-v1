# Atlas Editor Intelligence

Atlas shows Waset management the current performance picture of each Editor, explains it, and traces every conclusion back to Monday evidence.

## People and actors

**Editor**:
The only person Atlas evaluates in V1: whoever carries a project from In Progress to Ready For Approval.
_Avoid_: Assignee, employee, user

**Shared Account**:
The Monday account shown as `Waset Co`, used by several people, so its actions never identify a person by themselves.
_Avoid_: Waset Co user, actor (as a person)

**Transition Role**:
The role (Editor or Production Manager) responsible for a status change, determined by the exact transition rather than by who made it.
_Avoid_: Actor, performer

## Work and time

**Project**:
One Monday item worked on by an Editor; the unit in which sample sizes are counted.
_Avoid_: Task, job, pulse

**Work Cycle**:
A span from a project entering In Progress to it next reaching Ready For Approval.
_Avoid_: Job run, session

**Editor Work Time**:
The elapsed time of a Work Cycle.
_Avoid_: Turnaround, lead time, handling time

**Business Day**:
A calendar day in Cairo local time.
_Avoid_: UTC day, working day

**Current Window**:
The last 30 completed Business Days, not including today.
_Avoid_: Recent period, current month

**Comparison Window**:
The 30 completed Business Days immediately before the Current Window.
_Avoid_: Previous period, baseline

## Measurements

**Requested ETA**:
The delivery time requested in Monday that a project's first Ready For Approval is measured against.
_Avoid_: Deadline date, due date

**Deadline Delta**:
How far the first Ready For Approval fell before (early) or after (late) the Requested ETA.
_Avoid_: Delay, lateness score

**Video Type**:
The category of video a project is, which defines which projects may be compared for speed.
_Avoid_: Project type, format

**Team Benchmark**:
The typical Editor Work Time of the other Editors for one Video Type, never including the Editor being viewed; descriptive, never a target.
_Avoid_: SLA, standard time, expected time

**Active Work**:
Projects currently needing the Editor's action: In Progress, Client Revision or Internal Revision.
_Avoid_: Workload, load, capacity, current projects

**Awaiting Approval**:
Projects the Editor has submitted that wait on production review.
_Avoid_: Active Work, pending, in review

**Sample Size**:
The number of projects behind a figure.
_Avoid_: Volume, n

## Signals

**Quality Label**:
A performance label management puts on a project in Monday; one occurrence is one event.
_Avoid_: Performance issue, tag, flag

**Positive Label**:
A Quality Label that records good performance.
_Avoid_: Bonus label, For Bonus (a Monday column, not a category)

**Negative Label**:
A Quality Label that records a performance problem.
_Avoid_: Issue, penalty, strike

**Context Label**:
A Quality Label that describes circumstances and is neither good nor bad for the Editor.
_Avoid_: Neutral issue, info label

**Client Revision**:
A change requested by the client, recorded when a project enters Revisions; context only, never blamed on the Editor.
_Avoid_: Revision (unqualified), correction, editor mistake

**Internal Revision**:
A change requested inside Waset, recorded when a project enters Internal Revisions; context only, with no cause inferred.
_Avoid_: Reviewer rejection, QA fail, editor mistake

**Rework Time**:
Time spent on a project after a Client or Internal Revision; context only, never part of Editor Work Time.
_Avoid_: Revision speed, second cycle

## Interpretation

**Overall Status**:
The one-word summary of an Editor's current performance, looked up from the Component States of quality, speed and deadline only: Strong, Good, Mixed or Below Expectations.
_Avoid_: Score, rating, rank, Needs Attention, Under Pressure

**Component State**:
The reading of one scored component (Quality, Speed or Deadline): Positive, Neutral, Negative or Not classifiable.
_Avoid_: Sub-score, grade

**Strength**:
A supported positive finding inside the Current Window.
_Avoid_: Recognition, praise

**Attention Area**:
A supported negative finding inside the Current Window.
_Avoid_: Weakness, problem, Needs Attention Now

**Recognition**:
A flag raised by a material improvement from the Comparison Window to the Current Window.
_Avoid_: Strength, award

**Needs Attention Now**:
A flag raised by a material deterioration from the Comparison Window to the Current Window.
_Avoid_: Attention Area, warning, Needs Attention (as a status)

**Recent Change**:
The factual difference in a measurement between the Comparison Window and the Current Window.
_Avoid_: Trend, movement

**Trend**:
The rule-based reading of a Recent Change: Improving, Stable or Declining.
_Avoid_: Recent Change, direction

**Approved Threshold**:
A business cut-off the Atlas business owner has approved and recorded; nothing is classified without one.
_Avoid_: Default, heuristic, calibration value
