import flask
from flask import render_template
from flask import request
from flask import url_for
from free_times import calculate_free_times, sort, merge
import uuid
import json
import logging

# Date handling 
import arrow # Replacement for datetime, based on moment.js
# import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

# Mongo database
from pymongo import MongoClient

###
# Globals
###
import config
if __name__ == "__main__":
    CONFIG = config.configuration()
else:
    CONFIG = config.configuration(proxied=True)

app = flask.Flask(__name__)
app.debug=CONFIG.DEBUG
app.logger.setLevel(logging.DEBUG)
app.secret_key=CONFIG.SECRET_KEY

MONGO_CLIENT_URL = "mongodb://{}:{}@{}:{}/{}".format(
    CONFIG.DB_USER,
    CONFIG.DB_USER_PW,
    CONFIG.DB_HOST, 
    CONFIG.DB_PORT, 
    CONFIG.DB)

print("Using URL '{}'".format(MONGO_CLIENT_URL))

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = CONFIG.GOOGLE_KEY_FILE  ## You'll need this
APPLICATION_NAME = 'MeetMe class project'

####
# Database connection per server process
###

try: 
    dbclient = MongoClient(MONGO_CLIENT_URL)
    db = getattr(dbclient, CONFIG.DB)
    collection = db.dated

except:
    print("Failure opening database.  Is Mongo running? Correct password?")
    sys.exit(1)

#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route('/_startup', methods=['POST'])
def startup():
  """
  The startup page that either takes in a meeting id or allows you to create a new meeting.
  """
  app.logger.debug("Entering startup")
  meeting_id = flask.request.form.get("meeting_id")
  app.logger.debug("meeting_id = " + str(meeting_id))
  try:
    db_names = db.collection_names()
    if meeting_id in db_names:
      app.logger.debug("Found database entry")
      flask.g.does_not_exist = 1
      flask.session['meeting_id'] = meeting_id
      return flask.redirect(flask.url_for("choose"))
    elif meeting_id == None:
      flask.g.does_not_exist = 1
      return flask.render_template('startup.html')
    else:
      flask.g.does_not_exist = 2
      return flask.render_template('startup.html')
  except:
    app.logger.debug("Error finding collection or first time through")
    flask.g.does_not_exist = 1
  return flask.render_template('startup.html')

@app.route('/_new', methods=['POST'])
def new():
  """
  Creates a new meeting in the database based on the ID entered.
  """
  app.logger.debug("Entering new")
  new_meeting_id = flask.request.form.get("new_meeting_id")
  app.logger.debug("new_meeting_id = " + str(new_meeting_id))
  #try:
  db_names = db.collection_names()
  if new_meeting_id in db_names:
    app.logger.debug("ID already exists")
    flask.g.exists = 2
    return flask.render_template('startup.html')
  else:
    db.create_collection(new_meeting_id)
    flask.session['new_meeting_id'] = new_meeting_id
    flask.g.exists = 1
    return flask.render_template('index.html')
  #except:
    #app.logger.debug("Error finding collection or first time through")
    #flask.g.exists = 1
  return flask.render_template('startup.html')

@app.route('/invite', methods=['POST'])
def invite():
    """
    A page to invite other users to enter their google calendar to make a meeting with multiple people
    """
    return flask.render_template('invite.html')

@app.route("/index", methods=['POST'])
def index():
  app.logger.debug("Entering index")
  if 'begin_date' not in flask.session:
    init_session_values()
  return render_template('index.html')

@app.route("/choose")
def choose():
    ## We'll need authorization to list calendars 
    ## I wanted to put what follows into a function, but had
    ## to pull it back here because the redirect has to be a
    ## 'return' 
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")
    flask.g.calendars = list_calendars(gcal_service)
    return render_template('index.html')

@app.route("/_list", methods=["POST"])
def list():
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))
    gcal_service = get_gcal_service(credentials)
    flask.g.calendars = list_calendars(gcal_service)
    app.logger.debug("Printing list of times")
    selected_cals = flask.request.form.getlist("interest")
    try:
      # Initial setup
      session_begin_date = str(flask.session["begin_date"])[:10]
      collection_name = flask.session['new_meeting_id']
      datetime_dict = db[collection_name].find_one()
      app.logger.debug("datetime_dict = " + str(datetime_dict))
      session_begin_datetime = arrow.get(datetime_dict["begin_datetime"])
      session_end_datetime = arrow.get(datetime_dict["end_datetime"])
      app.logger.debug("session_begin_datetime = " + str(session_begin_datetime))
      app.logger.debug("session_end_datetime = " + str(session_end_datetime))
      initial_setup = True
    except:
      # Existing meeting
      initial_setup = False
      collection_name = flask.session['meeting_id']
      datetime_dict = db[collection_name].find_one()
      session_begin_datetime = arrow.get(datetime_dict["begin_datetime"])
      session_end_datetime = arrow.get(datetime_dict["end_datetime"])
      app.logger.debug("session_begin_datetime = " + str(session_begin_datetime))
      app.logger.debug("session_end_datetime = " + str(session_end_datetime))
    counter = 0
    for cal_str in selected_cals:
      for cal_obj in flask.g.calendars:
        if cal_obj['summary'] == cal_str:
          selected_cals[counter] = cal_obj
      counter += 1
    app.logger.debug("selected_cals = " + str(selected_cals))
    app.logger.debug("flask.g.calendars = " + str(flask.g.calendars))
    now = arrow.now()
    print('Getting the events.')
    finished_events = []
    finished_event_times = []
    for cal in selected_cals:
      eventsResult = gcal_service.events().list(
          calendarId=cal['id'], timeMin=now, maxResults=10, singleEvents=True,
          orderBy='startTime').execute()
      events = eventsResult.get('items', [])
      app.logger.debug("events = " + str(events))
      for i in events:
        try:
          if 'transparency' in i:
            app.logger.debug("Transparent event = " + i['summary'])
            continue
        except:
          app.logger.debug("Issue checking event transparncy in: " + i['summary'])
        try:
          if 'start' in i:
            if 'date' in i['start']:
              check_date = arrow.get(i['start']['date'], 'YYYY-MM-DD')
              if arrow.get(session_begin_datetime) <= check_date <= arrow.get(session_end_datetime): 
                finished_events.append(i)
                continue
            if 'dateTime' in i['start']:
              check_date = arrow.get(i['start']['dateTime'])
              if arrow.get(session_begin_datetime) <= check_date <= arrow.get(session_end_datetime):
                finished_events.append(i)
                finished_event_times.append([arrow.get(i['start']['dateTime']), arrow.get(i['end']['dateTime'])])
                continue
          if 'end' in i:
            if 'date' in i['end']:
              check_date = arrow.get(i['end']['date'], 'YYYY-MM-DD')
              if arrow.get(session_begin_datetime) <= check_date <= arrow.get(session_end_datetime): 
                finished_events.append(i)
                continue
            if 'dateTime' in i['end']:
              check_date = arrow.get(i['end']['dateTime'])
              if arrow.get(session_begin_datetime) <= check_date <= arrow.get(session_end_datetime):
                finished_events.append(i)
                finished_event_times.append([arrow.get(i['start']['dateTime']), arrow.get(i['end']['dateTime'])])
                continue
          app.logger.debug("Failed to parse time in event: " + i['summary'])
        except:
          app.logger.debug("Could not parse time in event: " + i['summary'])
    flask.g.list = finished_events
    ready_for_db = []
    if finished_event_times != []:
      for i in finished_event_times:
        inner_list = []
        for j in i:
          inner_list.append(str(j)[0:32])
        ready_for_db.append(inner_list)
    app.logger.debug("finished_event_times = " + str(finished_event_times))
    if initial_setup == False:
      to_be_added = db[collection_name].find()[1]['busytimes']
      busytimes_id = db[collection_name].find()[1]['_id']
      app.logger.debug("busytimes_id = " + str(busytimes_id))
      for i in eval(to_be_added):
        inner_list = []
        for j in eval(str(i)):
          inner_list.append(j)
        ready_for_db.append(inner_list)
      db[collection_name].update({"_id" : busytimes_id}, {"busytimes" : str(ready_for_db)})
    else:
      db[collection_name].insert({"busytimes" : str(ready_for_db)})
    all_db_event_times = []
    collection_busytimes = db[collection_name].find()[1]['busytimes']
    app.logger.debug("collection busytimes = " + str(collection_busytimes))
    finished_list = []
    for i in eval(collection_busytimes):
      inner_list = []
      for j in eval(str(i)):
        j = str(j).replace('T', ' ')
        j = (arrow.get(j), 'YYYY-MM-DD HH:mm:ssZZ')
        inner_list.append(j)
      finished_list.append(inner_list)
    free_times = calculate_free_times(finished_list, arrow.get(session_begin_datetime), arrow.get(session_end_datetime))
    final_free_times = []
    for se in free_times:
      sd = str(se[0])[9:19]
      st = str(se[0])[20:25]
      ed = str(se[1])[9:19]
      et = str(se[1])[20:25]
      final_free_times.append('{} at {} to {} at {}'.format(sd, st, ed, et))
    app.logger.debug("free_times = " + str(free_times))
    flask.g.free = final_free_times
    return render_template('index.html')

####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST: 
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable. 
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead. 
#
####

def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service

@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function. 
  
  ## The *second* time we enter here, it's a callback 
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1. 
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('choose'))

#####
#
#  Option setting:  Buttons or forms that add some
#     information into session state.  Don't do the
#     computation here; use of the information might
#     depend on what other information we have.
#   Setting an option sends us back to the main display
#      page, where we may put the new information to use. 
#
#####

@app.route('/setrange', methods=['POST'])
def setrange():
    """
    User chose a date range with the bootstrap daterange
    widget.
    """
    app.logger.debug("Entering setrange")  
    flask.flash("Setrange gave us '{}' '{}'".format(
      request.form.get('daterange'), request.form.get('timerange')))
    daterange = request.form.get('daterange')
    timerange = request.form.get('timerange')
    flask.session['daterange'] = daterange
    flask.session['timerange'] = timerange
    timerange_parts = timerange.split()
    flask.session['begin_time'] = interpret_time(timerange_parts[0])
    flask.session['end_time'] = interpret_time(timerange_parts[2])
    daterange_parts = daterange.split()
    flask.session['begin_date'] = interpret_date(daterange_parts[0])
    flask.session['end_date'] = interpret_date(daterange_parts[2])
    app.logger.debug("Setrange parsed {} - {}  dates as {} - {}".format(
      daterange_parts[0], daterange_parts[1], 
      flask.session['begin_date'], flask.session['end_date']))
    app.logger.debug("Setrange parsed {} - {}  dates as {} - {}".format(
      timerange_parts[0], timerange_parts[1], 
      flask.session['begin_time'], flask.session['end_time']))
    session_begin_date = str(flask.session["begin_date"])[:10]
    session_end_date = str(flask.session["end_date"])[:10]
    session_begin_time = str(flask.session["begin_time"])[11:16]
    session_end_time = str(flask.session["end_time"])[11:16]
    flask.session['session_begin_datetime'] = str(arrow.get(session_begin_date + ' ' + session_begin_time, 'YYYY-MM-DD HH:mm'))
    flask.session['session_end_datetime'] = str(arrow.get(session_end_date + ' ' + session_end_time, 'YYYY-MM-DD HH:mm'))
    collection_name = flask.session['new_meeting_id']
    db[collection_name].insert(
      {"begin_datetime" : str(flask.session['session_begin_datetime']), "end_datetime" : str(flask.session['session_end_datetime'])})
    return flask.redirect(flask.url_for("choose"))

@app.template_filter( 'humanize' )
def humanize_arrow_date( date ):
    """
    Taken from proj6-mongo
    Date is internal UTC ISO format string.
    Output should be "today", "yesterday", "in 5 days", etc.
    Arrow will try to humanize down to the minute, so we
    need to catch 'today' as a special case. 
    """
    try:
        then = arrow.get(date).to('local')
        now = arrow.utcnow().to('local')
        if then.date() == now.date():
            human = "Today"
        else: 
            human = then.humanize(now)
            if human == "in a day":
                human = "Tomorrow"
    except: 
        human = date
    return human

####
#
#   Initialize session variables 
#
####

def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main. 
    """
    # Default date span = tomorrow to 1 week from now
    now = arrow.now('local')     # We really should be using tz from browser
    tomorrow = now.replace(days=+1)
    nextweek = now.replace(days=+7)
    flask.session["begin_date"] = tomorrow.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        tomorrow.format("MM/DD/YYYY"),
        nextweek.format("MM/DD/YYYY"))
    # Default time span each day, 8 to 5
    flask.session["begin_time"] = interpret_time("9am")
    flask.session["end_time"] = interpret_time("5pm")

def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    app.logger.debug("Decoding time '{}'".format(text))
    time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try: 
        as_arrow = arrow.get(text, time_formats).replace(tzinfo=tz.tzlocal())
        as_arrow = as_arrow.replace(year=2016) #HACK see below
        app.logger.debug("Succeeded interpreting time")
    except:
        app.logger.debug("Failed to interpret time")
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
              .format(text))
        raise
    return as_arrow.isoformat()
    #HACK #Workaround
    # isoformat() on raspberry Pi does not work for some dates
    # far from now.  It will fail with an overflow from time stamp out
    # of range while checking for daylight savings time.  Workaround is
    # to force the date-time combination into the year 2016, which seems to
    # get the timestamp into a reasonable range. This workaround should be
    # removed when Arrow or Dateutil.tz is fixed.
    # FIXME: Remove the workaround when arrow is fixed (but only after testing
    # on raspberry Pi --- failure is likely due to 32-bit integers on that platform)


def interpret_date( text ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
          tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

####
#
#  Functions (NOT pages) that return some information
#
####
  
def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict.
    The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        if "description" in cal: 
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]
        

        result.append(
          { "kind": kind,
            "id": id,
            "summary": summary,
            "selected": selected,
            "primary": primary
            })
    return sorted(result, key=cal_sort_key)


def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])


#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("HH:mm")
    except:
        return "(bad time)"
    
#############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running under green unicorn)
  app.run(port=CONFIG.PORT,host="0.0.0.0")
    
