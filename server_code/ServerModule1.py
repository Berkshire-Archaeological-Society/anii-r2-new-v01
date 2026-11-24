##!/usr/local/bin/python
##
# Anvil-Uplink server      
# provides callable functions for Anvil Webapp
# this is now in a github repository https://github.com/Berkshire-Archaeological-Society/anii-r2-server.git
##
# Version 096

##      
# Author: Tony Bakker (BAS)
#
#################################################### 
#
# import generic stuff and special installed modules      
#
import os
import sys
import pymysql
from pymysql.constants import FIELD_TYPE
import csv
import logging
import os
import json
import gzip
import shutil
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timezone, timedelta
import uuid
import pandas as pd
import numpy as np
import configparser
import bcrypt
import smtplib
import yaml
import re
import gc
import sqlparse
from email.message import EmailMessage
from email_validator import validate_email, EmailNotValidError

#import anvil modules
#from anvil.users import UserExistsError
import anvil.server
import anvil.users
import anvil.email
import anvil.tables as tables
import anvil.tables.query as q
import anvil.secrets
import anvil.media
import anvil.pdf
#from anvil.pdf import PDFRenderer
#from anvil.pdf import PdfRenderer
from anvil.tables import app_tables

# Dynamically finds the folder containing this server script and append it to the sys.path
# doing this to be able to add client module to the server code (especially the DataValidation module)
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

#import DataValidation     # yet to be tested

# ------------------
# GLOBAL definitions
# ------------------
# extension definitions for txt and rtf column names (must be same length!)
TX_EXTENSION = "Txt"
RT_EXTENSION = "Rtf"
ALLOWED_EXTENSIONS = (TX_EXTENSION, RT_EXTENSION)
# set the list of DB procedures allowed to be called form the query table
ALLOWED_CALLS = {"CALL search_any_table"}
# delta time in minutes for onlibe activity
ONLINE_DELTA_TIME = 5

############# Defining all the Functions #############

# ---------------------------------------
# Generic functions (not client callable)
# ---------------------------------------

def hash_password(password, salt):
  """Hash the password using bcrypt in a way that is compatible with Python 2 and 3."""
  if not isinstance(password, bytes):
    password = password.encode()
  if not isinstance(salt, bytes):
    salt = salt.encode()

  result = bcrypt.hashpw(password, salt)

  if isinstance(result, bytes):
    return result.decode('utf-8')

def is_safe_sql(sql_str: str):
  #
  # This function check if the SQL command string is safe using sql_parse and allowed SQL commands
  #
  # 1. Remove all comments and leading/trailing whitespace
  logmsg("DEBUG",f"SQL command to check is: {sql_str}")
  clean_sql = sqlparse.format(sql_str, strip_comments=True).strip()
    
  if not clean_sql:
    logmsg("DEBUG","FAIL: error in sqlparse removing all comments and leading/trailing whitespace")
    return False  # Empty query after comment removal
    
  # 2. Parse the sanitized string into statements
  parsed = sqlparse.parse(clean_sql)
  if not parsed:
    logmsg("DEBUG","FAIL: error in sqlparse Parse the sanitized string into statements")
    return False
    
  statement = parsed[0]
  logmsg("DEBUG","sql safety statement is "+str(statement))

  # Ensure it's a single query (prevents SQL injection via statement chaining)
  if len(parsed) > 1:
    logmsg("DEBUG","FAIL: sql command is not a single query")
    return False
        
  # 1. Get the first non-whitespace token
  first_token = next((t for t in statement.tokens if not t.is_whitespace and t.ttype is not sqlparse.tokens.Comment), None)
    
  if not first_token:
    return False
        
  verb = first_token.value.upper()
  
  # Get the command type (e.g., 'SELECT', 'CALL')
  #command_type = statement.get_type().upper()

  logmsg("DEBUG","sql safety check first verb is "+verb)
  # 3. Validate against allowed rules
  if verb == "SELECT":
    logmsg("DEBUG","OK. sql command safety check passed: SELECT")
    return True
        
  if verb == "CALL":
    # Check against a strict whitelist of allowed procedure calls
    normalized = " ".join(clean_sql.split())  # Collapse multiple spaces
    if any(normalized.upper().startswith(allowed.upper()) for allowed in ALLOWED_CALLS):
      logmsg("DEBUG","OK. sql command safety check passed: CALL")
      return True
    else:
      logmsg("DEBUG","OK. sql command safety check failed: CALL to unknown procedure.")
      return False
    
  logmsg("DEBUG","FAIL: sql safety check fell through all allowed rules and defaulted to Fail.")
  return False

####################################
# This is the DataValidation section
####################################

#def validate_email(email):
#  pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
#  if not email or not re.match(pattern, str(email).strip()):
#    return False, "Invalid email address format."
#  return True, ""

def check_email(email_str):
  #
  # This function check the structure of the email_str and if the domain exists.
  #
  try:
    # Check structure and verify the domain has valid DNS records
    email_info = validate_email(email_str, check_deliverability=True)
        
    # Returns the normalized, safely formatted email string
    return True, f"Valid: {email_info.normalized}"
        
  except EmailNotValidError as e:
    # Returns the specific reason why the email failed validation
    return False, f"Invalid email format for {email_str}: {str(e)}"


def validate_integer(number):
  #
  # This function check if number is a valid integer number 
  #
  pattern = r"^$|^\d*$"
  if not number or not re.match(pattern, str(number).strip()):
    return False, f"Invalid whole number format: {number}"
  return True, ""

def validate_year(number):
  #
  # This function checks if the number is a valid year format
  #

  # Convert number to string and clean whitespace
  num_str = "" if number is None else str(number).strip()

  #  Allow empty strings (valid for optional fields)
  if num_str == "":
    return True, ""
  #
  pattern = r"^$|^(-?[0-9]{1,10}|)$"
  if not number or not re.match(pattern, str(number).strip()):
    return False, f"Invalid year format: {number}."
  return True, ""

def validate_percentage(number):
  # 
  # This function check if the number  is a valid percentage format 999.99
  #
  #pattern = r"^(100(\.0+)?|[1-9]?\d(\.\d+)?)$" 
  pattern = r"^(?:100(?:\.0{1,3})?|(?:[1-9]?[0-9])(?:\.[0-9]{1,3})?)$"
  if not number or not re.match(pattern, str(number).strip()):
    return False, f"Invalid percentage format: {number}"
  return True, ""

def validate_BNGRcentroid(coordinate_string):
  #
  # This function check if coordinate_string is a valid BNGRcentroid format
  #

  # Strict regex enforcing matching digit lengths (2, 3, 4, or 5 digits) for both parts
  BNGR_PATTERN = re.compile(
    r"^(?P<GridSq>[HJKLMNOQRSTVWXYZ][A-HJ-Z])\s*"
    r"(?:"
    r"(?P<E2>\d{2})\s*(?P<N2>\d{2})|"   # 4-figure ref (10km accuracy)
    r"(?P<E3>\d{3})\s*(?P<N3>\d{3})|"   # 6-figure ref (1km accuracy)
    r"(?P<E4>\d{4})\s*(?P<N4>\d{4})|"   # 8-figure ref (100m accuracy)
    r"(?P<E5>\d{5})\s*(?P<N5>\d{5})"    # 10-figure ref (1m accuracy)
    r")$",
    re.IGNORECASE
  )
  # Strip whitespace and match against the strict pattern
  match = BNGR_PATTERN.match(coordinate_string.strip())

  if not match:
    return False, f"'{coordinate_string}' is not a valid BNG centroid format."  # Invalid layout or mismatched precision length

  gd = match.groupdict()
  grid_square = gd['GridSq'].upper()

  # Coalesce the capture groups to find which specific precision length matched
  easting = gd['E2'] or gd['E3'] or gd['E4'] or gd['E5']
  northing = gd['N2'] or gd['N3'] or gd['N4'] or gd['N5']
  details = {
    "grid_square": grid_square,
    "easting": easting,
    "northing": northing,
    "precision_meters": 10**(5 - len(easting)) * 10 # Calculates actual ground precision
  }
  return True, details

def validate_decimal(number, data_type):
  #
  # This functions check of the number is a valid decimal, float, double number with the given precision in data_type
  #
  data_type_lower = data_type.lower()
  
  # Convert number to string and clean whitespace
  num_str = "" if number is None else str(number).strip()

  # Check if data_type belongs to numeric floating/decimal types
  if any(dt in data_type_lower for dt in ["decimal", "float", "double"]):

    # Extract dimensions (e.g., 'decimal(6,2)' -> [6, 2])
    dec_type = [int(n) for n in re.findall(r'\d+', data_type)]

    if len(dec_type) >= 2:
      # 1. Parameterized type: e.g. DECIMAL(M, D) or FLOAT(M, D)
      max_digits = dec_type[0]
      decimal_places = dec_type[1]
      integer_digits = max_digits - decimal_places

      # Prevent negative or zero integer digit length
      if integer_digits <= 0:
        return False, f"Invalid schema precision specification: {data_type}"

      pattern = rf"^$|^-?\d{{1,{integer_digits}}}(\.\d{{1,{decimal_places}}})?$"
      
    elif len(dec_type) == 1:
      # 2. Single precision specified: e.g. FLOAT(p)
      max_digits = dec_type[0]
      pattern = rf"^-?\d{{1,{max_digits}}}(\.\d+)?$"

    else:
      # 3. Unparameterized type: e.g. FLOAT or DOUBLE
      pattern = r"^-?\d+(\.\d+)?$"

    #  Allow empty strings (valid for optional fields)
    if num_str == "":
      return True, ""
    
    if re.match(pattern, num_str):
      return True, ""
    return False, f"Invalid format for {data_type} {number}."

  return False, "Unknown data type."


def validate_row(row,site_id,table_info,table_name):
  # 
  # This function will validate the values of the columns in a row.
  #

  logmsg("DEBUG","Entering validate_row")
  logmsg("DEBUG",row)
  #logmsg("DEBUG",table_info)

  # 1. Create a quick lookup mapping: column_name -> column_type
  schema_types = {col['COLUMN_NAME']: col['COLUMN_TYPE'] for col in table_info}
  schema_keys =  {col['COLUMN_NAME']: col['COLUMN_KEY'] for col in table_info}
  schema_is_nullable =  {col['COLUMN_NAME']: col['IS_NULLABLE'] for col in table_info}

  # 2. Extract column types for each key in your data dictionary
  column_type_mapping = {key: schema_types.get(key) for key in row}

  meta_data = CONFIG["CLIENT"]["table_column_meta_data"]

  msg = ""
  return_value = True
  for column_name, value in row.items():
    try:
      raw_type = schema_types.get(column_name)
      if raw_type is None:
        logmsg("ERROR", f"Column '{column_name}' not found in table_info schema")
        return False, f"Unknown column: {column_name}", row

      column_type = raw_type.lower()
      column_key = schema_keys.get(column_name)
      column_is_nullable = schema_is_nullable.get(column_name) in (True, "YES", "yes", 1)
      col_meta = (meta_data.get(table_name) or {}).get(column_name) or {}
      col_meta_type = col_meta.get("type")
    
      is_valid = True
      err_msg = ""

      #logmsg("DEBUG",f"Column {column_name}, value {value}, type {column_type}, key {column_key}, nullable {column_is_nullable}")
     
      if column_name == "SiteId" and value != site_id:
        # can only add records for selected site_id
        is_valid = False
        err_msg = f"Invalid Site_Id {value} for this row. Can only add rows for selected site with ID {site_id}."

      elif (value == "" or value is None) and not column_is_nullable:
        # empty value for non nullable collumn is an error; for PRI keys the catchall test below will catch an empty PRI value and fail
        is_valid = False
        err_msg = f"Column {column_name} cannot be empty."

      elif (value == "" or value is None) and column_is_nullable:
        # empty value for nullable collumn is ok
        is_valid = True

      # check for list of multi_select
      elif (
          table_name in meta_data
          and column_name in meta_data[table_name]
          and col_meta.get("type") in ["list","multi_select"]
         ):
        # value has to be one or more (comma separated) elements in the list 
       
        # Convert incoming user value into a set of clean strings
        # Split, strip, and capitalize each item individually
        cap_items = [
          item.strip().capitalize()
          for item in str(value).split(",")
          if item.strip()
        ]
        input_set = set(cap_items)
        #input_set = {item.strip() for item in str(value).split(",") if item.strip()}
        # 3. Check if all input values exist in the allowed set
        if input_set.issubset(col_meta.get("options",[])) or col_meta.get("allow_other"):
          is_valid = True
          row[column_name] = ", ".join(cap_items)
        else:
          is_valid = False
          err_msg = f"Invalid value {value} for {column_name}."
      
      elif (
          table_name in meta_data
          and column_name in meta_data[table_name]
          and col_meta.get("type") in ["dropdown","single_select"]
         ):
        # check for dropdown or single_select; value has to be one of the options defined for this column
        cap_value = str(value).strip().capitalize()
        if cap_value in col_meta.get("options", []) or col_meta.get("allow_other"):
          is_valid = True
          row[column_name] = cap_value
        else:
          is_valid = False
          err_msg = f"Invalid value {cap_value} for {column_name}."

      elif ("year" in column_name.lower()
          or (table_name in meta_data
              and column_name in meta_data[table_name]
              and col_meta.get("type") == "year"
             )
         ): # check for year in column_name
        # elif column_name in ["YearEnd","YearStart","Year","ContextYear","SurveyYear"]: # in principal any column with Year in name
        is_valid, err_msg = validate_year(value)

      elif (column_name.lower() == "email"
          or (table_name in meta_data
              and column_name in meta_data[table_name]
              and col_meta.get("type") == "email"
             )
         ):
        is_valid, err_msg = validate_email(value)

      elif (column_name == "BNGRcentroid"
          or (table_name in meta_data
              and column_name in meta_data[table_name]
              and col_meta.get("type") == "BNGRcentroid"
             )
         ):
        is_valid, err_msg = validate_BNGRcentroid(value)

      elif (column_name.endswith("Percentage")
          or (table_name in meta_data
              and column_name in meta_data[table_name]
              and col_meta.get("type") == "percentage"
             )
         ): 
        # any column name ending on Percentage
        is_valid, err_msg = validate_percentage(value)

      # checks for int and decimal (float, double) are based on database table columns datatype
      elif "int" in column_type:
        is_valid, err_msg = validate_integer(value)

      elif any(t in column_type.lower() for t in ["decimal", "float", "double"]):
        is_valid, err_msg = validate_decimal(value, column_type)

      # catchall for empty Primary key column
      if column_key == "PRI" and (value == "" or value is None):
        # error - primary key cannot be empty;
        # this check should include <table_name>Id column as it should be a PRI key
        is_valid = False
        err_msg = "Primary key cannot be empty."
    
      # if any check failed set the return_value to be False
      # and add err_msg of check to the msg to be returned
      if not is_valid: 
        return_value = False
        msg = msg + column_name + ": " + err_msg + ", "

    except Exception as e:
      import traceback
      logmsg("ERROR", f"Crash validating column '{column_name}' with value '{value}': {e}\n{traceback.format_exc()}")
      raise
  logmsg("DEBUG",msg)
  return return_value,msg,row

def dict_get(data, keys, default=None):
  #
  # This function is used to check data of the configuration file 
  #
  # """Recursively traverse dictionary keys, returning default if any key is missing or None."""

  for key in keys:
    if isinstance(data, dict):
      data = data.get(key)
    else:
      return default
    if data is None:
      return default
  return data

def dict_ensure_list_items(data_dict, key_path, required_items):
    #
    # This function is used to check data of the configuration file 
    #
    # Ensures a nested key path exists as a list containing required_items.
    # 'key_path' can be a single key ("key") or a sequence of nested keys (["CLIENT", "TextArea_columns"]).
    # 
    # Standardize required_items into a list
    if isinstance(required_items, (str, bytes)) or not hasattr(required_items, '__iter__'):
        required_items = [required_items]

    # Standardize key_path into a list of keys
    if isinstance(key_path, str):
        keys = [key_path]
    else:
        keys = list(key_path)

    # 1. Traverse or build the nested dictionary hierarchy
    current_level = data_dict
    for key in keys[:-1]:
        if key not in current_level or not isinstance(current_level[key], dict):
            current_level[key] = {}
        current_level = current_level[key]

    target_key = keys[-1]

    # 2. Retrieve existing list or initialize
    current_val = current_level.get(target_key)
    if not isinstance(current_val, list):
        current_val = []

    # 3. Add missing required items
    for item in required_items:
        if item not in current_val:
            current_val.append(item)

    # 4. Save updated list back
    current_level[target_key] = current_val

def dict_merge_nested_structure(data_dict, key_path, new_tables_dict):
    #
    # This function is used to check data of the configuration file 
    #    
    # Navigates to a nested key path and merges a dictionary of tables
    # and columns into it, preventing duplicates in the lists.
    #
    # 1. Standardize key_path into a list of keys
    if isinstance(key_path, str):
        keys = [key_path]
    else:
        keys = list(key_path)

    # 2. Traverse or build the nested dictionary hierarchy
    current_level = data_dict
    for key in keys:
        if key not in current_level or not isinstance(current_level[key], dict):
            current_level[key] = {}
        current_level = current_level[key]

    # 3. 'current_level' is now pointing exactly at the destination (e.g., TextArea_columns)
    # Merge the new tables and their columns into it
    for table_name, columns in new_tables_dict.items():
        # Ensure columns are a list
        if isinstance(columns, (str, bytes)) or not hasattr(columns, "__iter__"):
            columns = [columns]

        # Initialize the table list if it doesn't exist
        if table_name not in current_level or not isinstance(
            current_level[table_name], list
        ):
            current_level[table_name] = []

        # Append column names safely without adding duplicates
        for col in columns:
            if col not in current_level[table_name]:
                current_level[table_name].append(col)

def convert_date(pdf, output_format='%d-%m-%Y'):
    # 1. Catch true datetime64 and timezone-aware datetime columns
    all_date_cols = list(pdf.select_dtypes(include=['datetime', 'datetimetz']).columns)
    
    # 2. Scan object/string columns safely
    for col in pdf.select_dtypes(include=['object', 'string']).columns:
        col_str = str(col).lower()
        non_null = pdf[col].dropna()
        
        if col_str.endswith(ALLOWED_EXTENSIONS) or non_null.empty:
            continue
            
        sample = non_null.head(10).astype(str).str.strip()
        
        # Skip pure numeric strings (like zip codes or IDs)
        if sample.str.isnumeric().all():
            continue
            
        # Must contain at least one digit AND a date separator (-, /, ., comma, or space)
        has_digits = sample.str.contains(r'\d', regex=True).all()
        has_separators = sample.str.contains(r'[-/.,\s]', regex=True).all()
        
        if not (has_digits and has_separators):
            continue

        # Parse sample with dayfirst=True to respect dd-mm-yyyy inputs
        parsed_sample = pd.to_datetime(sample, dayfirst=True, format='mixed', errors='coerce')
        
        # Require ALL sampled rows (not just 1) to be valid dates before converting the whole column
        if parsed_sample.notna().all():
            all_date_cols.append(col)

    # 3. Convert and format globally
    for col in all_date_cols:
        pdf[col] = (
            pd.to_datetime(pdf[col], dayfirst=True, format='mixed', errors='coerce')
            .dt.strftime(output_format)
            .fillna('')
        )
        
    return pdf


#def convert_date(pdf):
#
#  # start conversion of pdf fields of yyyy-mm-dd to dd-mm-yyyy
#  # 1. Identify true datetime64 pandas types (timestamps, datetime)
#  all_date_cols  = list(pdf.select_dtypes(include=['datetime64']).columns)
#  
#  # 2. Dynamically scan 'object' (text/mixed) columns for hidden database dates
#  for col in pdf.select_dtypes(include=['object']).columns:
#    # Check if the column is a string type and make it lowercase
#    col_str = str(col).lower()
#        
#    # CRITICAL SAFETY: Skip any column ending in Rtf or Txt, or if it is empty
#    if col_str.endswith(ALLOWED_EXTENSIONS) or pdf[col].dropna().empty:
#      continue
#    
#    # Sample the first (5) few non-null rows to see if they look like dates
#    sample_series = pd.to_datetime(pdf[col].dropna().head(5), errors='coerce')
#        
#    # If the sample converts cleanly to datetimes, add it to our list
#    if not sample_series.isna().all():
#      all_date_cols.append(col)
#
#  # 3. Apply the dd-mm-yyyy string formatting globally
#  for col in all_date_cols:
#    pdf[col] = pd.to_datetime(pdf[col], errors='coerce').dt.strftime('%d-%m-%Y')
#    # Clean up any NaT (Not a Time) missing data markers for Anvil
#    pdf[col] = pdf[col].fillna('')
#  
#  # end of conversion of yyyy-mm-dd to dd-mm-yyyy fields
#  return pdf

def table_update(site_id,table_name,table):
  # 
  # This is only for DB tables (not (yet) Anvil tables)
  #
  # This function will update rows of a table (pandas dataframe) into the database, containing one or more rows
  # (table_name is used to generate the (primary key) table_name_id (capitalize, strip last char and add Id, e.g. Table_name = Contexts, table_name_id will be ContextId))
  # table is a pandas dataframe 
  #
  logmsg("DEBUG","Entering table_update")
  logmsg("DEBUG",table)
  conn.ping(reconnect=True)

  # clean the table fields
  # 1. Standardize non-standard spaces (\xa0) and convert whitespace-only strings to NaN
  table.replace(r"\xa0", " ", regex=True, inplace=True)
  table.replace(r"^\s*$", np.nan, regex=True, inplace=True)
  
  # 2. Strip leading/trailing spaces from all object (string) columns
  string_cols = table.select_dtypes(include=["object","string"]).columns
  #table[string_cols] = table[string_cols].apply(lambda col: col.str.strip())
  table[string_cols] = table[string_cols].map(lambda x: x.strip() if isinstance(x, str) else x)

  # 3. Convert all NaN values to None at the end
  table = table.replace({np.nan: None})
  
  # creating column list for insertion: column names in table must be equal to database table column names
  #cols = "`,`".join([str(i) for i in table.columns.tolist()])
 
  # get table description
  table_info = describe_table(table_name)

  if table_name == "siteuserrole":
    # special case for siteuserrole table
    # set table_name_id to UserShortId 
    table_name_id = "UserShortId"
    #table['Email'] = table['Email'].str.lower()
  elif table_name.rfind(database_connect_info["special_finds_table_prefix"],0,2) != -1:
    # Any table starting with special_finds_table_prefix (e.g fs) has table_name_id as FindId
    table_name_id = "FindId"
  else:
    # all other tables will have the table_name_id set to "<table_name>Id"
    table_name_id = table_name.capitalize() + "Id"

  cur = conn.cursor()
  message = ""
  msg = ""
  # 
  # change pandas dataframe to list of records (dictionaries) for processing
  records = table.to_dict('records')
  row_nr = 1 
  for row in records:
    # first row in csv file is 2
    row_nr += 1
    logmsg("DEBUG","Update Row: ")
    logmsg("DEBUG",row)
    
    # validate row values
    is_valid, err_msg,updated_row = validate_row(row,site_id,table_info,table_name)
    if not is_valid:
      msg = f"Row {row_nr}: {table_name} {table_name_id} update to database failed - data validation errors: {err_msg}"
      logmsg("ERROR", msg)
      msg = f"ERROR. {msg}"
      message += msg + "\n"
      continue # validation failed, goto next row

    new_values = ""
    where_clause = ""
    where_cols = []
    where_cols_values = []
    cols = []
    cols_values = []
    for col in table.columns.tolist(): 
      column_info = next((column for column in table_info if column['COLUMN_NAME'] == col), None)
      if column_info["COLUMN_KEY"] == "PRI":
        # build WHERE clause with PRI keys
        where_cols.append(col)
        where_cols_values.append(str(updated_row[col]))
        where_clause = where_clause + col + " = %s AND "
      else:
        cols.append(col)
        new_values = new_values + col + " = %s,"
        if str(updated_row[col]) == "None": 
          cols_values.append(None)
        else:
          cols_values.append(str(updated_row[col]))

    # remove final ',' from new_values
    col_values = new_values.rstrip(",")
    # remove final AND from WHERE clause
    where_clause_clean = where_clause.rstrip(" AND ")
    # 
    all_values = cols_values + where_cols_values
    sql_cmd = "UPDATE `" + table_name.lower() + "` SET " + col_values + " WHERE " + where_clause_clean
    logmsg("DEBUG",sql_cmd)
    logmsg("DEBUG",all_values)
    try:
       ret = cur.execute(sql_cmd,all_values)
       logmsg("DEBUG",ret)
       conn.commit()
       msg = "OK. " + table_name +  table_name_id + " " + " " + updated_row[table_name_id] + " successfully updated."
       logmsg("INFO",msg)
    except pymysql.Error as err:
      err_msg = format(err)
      logmsg("DEBUG",err_msg)
      # .get() prevents KeyError; f-strings handle non-string data types safely
      row_id = updated_row.get(table_name_id, "<unknown id>") 
      msg = f"Row {row_nr}: {table_name} {table_name_id} {row_id} update to database failed: {err_msg}"
      logmsg("ERROR", msg)
      msg = f"ERROR. {msg}"
    message += msg + "\n"

  logmsg("DEBUG","Exiting table_update")  
  return message

def table_insert(site_id,table_name,table,admin_user,session_id):
  # 
  # This function will insert a table (pandas dataframe) into the database, containing one or more rows
  # (table_name is used to generate the table_name_id (capitalize, strip last char and add Id, e.g. Table_name = Contexts, table_name_id will be ContextId))
  # table is a pandas dataframe 
  #
  #logmsg("DEBUG",table)
  conn.ping(reconnect=True)
  
  # clean the table fields
  # 1. Standardize non-standard spaces (\xa0) and convert whitespace-only strings to NaN
  table.replace(r"\xa0", " ", regex=True, inplace=True)
  table.replace(r"^\s*$", np.nan, regex=True, inplace=True)
  
  # 2. Strip leading/trailing spaces from all object (string) columns
  string_cols = table.select_dtypes(include=["object","string"]).columns
  #table[string_cols] = table[string_cols].apply(lambda col: col.str.strip())
  table[string_cols] = table[string_cols].map(lambda x: x.strip() if isinstance(x, str) else x)

  # 3. Convert all NaN values to None at the end
  table = table.replace({np.nan: None})
  
  cols = "`,`".join([str(i) for i in table.columns.tolist()])
    
  # get table description
  table_info = describe_table(table_name)

  if table_name == "siteuserrole":
    # special case for siteuserrole table
    # set table_name_id to UserShortId 
    table_name_id = "UserShortId"
    #table['Email'] = table['Email'].str.lower()
  elif table_name.rfind(database_connect_info["special_finds_table_prefix"],0,2) != -1:
    # Any table starting with special_finds_table_prefix (e.g fs) has table_name_id as FindId
    table_name_id = "FindId"
  else:
    # all other tables will have the table_name_id set to "<table_name>Id"
    table_name_id = table_name.capitalize() + "Id"

  cur = conn.cursor()
  message = ""
  msg = ""
  #admin_user = anvil.users.get_user()
  #
  if anvil.server.context.background_task_id is not None:
    anvil.server.task_state['progress'] = 0
    anvil.server.task_state['logs'] = ["Import initialized..."]

  # change pandas dataframe to list of records (dictionaries) for processing
  records = table.to_dict('records')
  total_rows = len(records)
  log_buffer = []
  # 
  row_nr = 0
  for row in records:
    try:
      row_nr += 1
      #logmsg("DEBUG","New row: ")
      #logmsg("DEBUG",row)

      # validate row values
      is_valid, err_msg, updated_row = validate_row(row,site_id,table_info,table_name)
      if not is_valid:
        msg = f"Row {row_nr}: {table_name} {table_name_id} update to database failed: {err_msg}"
        logmsg("ERROR", msg)
        msg = f"ERROR. {msg}"
        message += msg + "\n"
        log_buffer.append(msg)
        continue # validation failed, goto next row

      # check if UserShortId is registered in Anvil users table
      if table_name == "siteuserrole":
        # special case for siteuserrole table
        # check if UserShortId is registered in Anvil users table
        anviluser = app_tables.users.get(initials = updated_row["UserShortId"])
        if anviluser is None:
          msg = f"ERROR. Row {row_nr}: siteuserrole row insert failed: UserShortId {updated_row["UserShortId"]} is not registered in system users table."
          logmsg("ERROR", msg)
          message = message + msg + "\n"
          log_buffer.append(msg)
          continue # with next row
    
      # Now check if table is a special find table (name starts with special_finds_table_prefix)
      #   if so check to see if findId exists in find table
      #     if findId exists than special find entry fails
      #       if findId does not exist, then we add the findId to the find table
    
      findsreg_tablename = dict_get(CONFIG,["DATABASE","findsregister_tablename"],default="findsregister")
    
      if table_name.lower().startswith(database_connect_info["special_finds_table_prefix"]):
        # check if FindId exists in findsregister table
        sql_cmd = f"SELECT 1 FROM `{findsreg_tablename}` WHERE FindId = %s LIMIT 1;"
        findid_value = updated_row["FindId"]

        try:
          cur.execute(sql_cmd,[findid_value])
          result = cur.fetchone()
          logmsg("DEBUG", f"Search result for FindId in findsregister: {str(result)}")
          if result is None:
            # there is no findId record found so we can create one in the findsregister
            # generate cols and values for find insert
            # build values list for findsregister entry
            findsreg_cols = ["SiteId", "ContextId","FindId", "FindsTable", "Material", "DBAcontrol"]
            Material = "" # not sure where to get this info from 
            findsreg_values = [updated_row["SiteId"],updated_row["ContextId"],updated_row["FindId"],table_name,Material,updated_row["DBAcontrol"]]
            # Join columns with backticks: `SiteId`, `ContextId`, `FindId`, ...
            cols_str = ", ".join(f"`{col}`" for col in findsreg_cols)
            sql_cmd = f"INSERT INTO `{findsreg_tablename}` ({cols_str}) VALUES (" + "%s,"*(len(findsreg_values)-1) + "%s)"
            logmsg("DEBUG",f"{sql_cmd},{findsreg_values}")
            try:
              ret = cur.execute(sql_cmd,findsreg_values)
              conn.commit()
              msg = f"OK. Row {row_nr}: Successfully inserted a new findsregister record (FindId {findid_value})."
              logmsg("INFO",msg)
              log_buffer.append(msg)
            except pymysql.Error as err:
              err_msg = format(err)
              logmsg("DEBUG",f"Error in adding FindId to findsregister table: {err_msg}")
              # .get() prevents KeyError; f-strings handle non-string data types safely
              row_id = updated_row.get(table_name_id, "<unknown id>") 
              msg = f"Row {row_nr}: {table_name} {table_name_id} {row_id} insert to database failed: {err_msg}"
              logmsg("ERROR", msg)
              msg = f"ERROR. {msg}"
              message = message + msg + "\n"
              log_buffer.append(msg)
              continue # with next row
          else:
            # found FindId record in finds register
            msg = f"ERROR. Row {row_nr}: Failed to insert the entry to {table_name}. FindId {findid_value} already exists in "+ findsreg_tablename + "."
            logmsg("ERROR",msg)
            message = message + msg + "\n"
            log_buffer.append(msg)
            continue # terminate current loop and continue with next row
        except pymysql.MySQLError as e:
          msg = f"Database error row {row_nr}:: {e}"
          logmsg("DEBUG",msg)
          message = message + msg + "\n"
          log_buffer.append(msg)
          continue # terminate current loop
    
      # now continue inserting new record in table
      sql_cmd = f"INSERT INTO `{table_name.lower()}` (`{cols}`) VALUES (" + "%s,"*(len(updated_row)-1) + "%s)"
      logmsg("DEBUG",sql_cmd)
      logmsg("DEBUG",list(updated_row.values()))
      try:
        ret = cur.execute(sql_cmd,list(updated_row.values()))
        logmsg("DEBUG",ret)
        conn.commit()
        row_id = updated_row.get(table_name_id, "N/A")
        msg = f"OK. Row {row_nr}: {table_name} {table_name_id} {row_id} successfully inserted."
        logmsg("INFO",msg)
        if table_name == "siteuserrole":
          #send email notification to user about access to site
          email_msg = ("\nDear %s,\n\n"
           "This is to notify you that you have been registered to access site %s in the role of %s of the Anchurus-II system for %s (%s)\n\n"
           "For exact details of your role please login to the above website and click on Help and read the relevant section of the Anchurus II user manual.\n\n"
           "Best wishes,\n\n"
           "%s %s - %s\n\n"
           % (anviluser["firstname"],updated_row["SiteId"],updated_row["Role"],Global_organisation,anvil.server.get_app_origin(),admin_user["firstname"],admin_user["lastname"],admin_user["email"]))
          subject = ("Registration to access site %s for Anchurus-II system %s" % (updated_row["SiteId"],Global_organisation))
          anvil.server.call("send_email",subject,email_msg,anviluser["email"],admin_user["email"])
          logmsg("DEBUG","Send notification email to user "+anviluser["email"])
      except pymysql.Error as err:
        err_msg = format(err)
        logmsg("DEBUG",err_msg)
        # .get() prevents KeyError; f-strings handle non-string data types safely
        row_id = updated_row.get(table_name_id, "<unknown id>") 
        msg = f"Row {row_nr}: {table_name} {table_name_id} {row_id} insert to database failed: {err_msg}"
        logmsg("ERROR", msg)
        msg = f"ERROR. {msg}"
        # delete findId from findsregister if row insert failure was for a special finds table
        if table_name.lower().startswith(database_connect_info["special_finds_table_prefix"]):
          row = {"FindId": findid_value}
          #user = anvil.users.get_user()
          delete_row("findsregister", row, admin_user["email"],session_id)
      
    finally: # Runs at the end of every iteration (whether standard finish or continue)
      message += msg + "\n"
      log_buffer.append(msg)
      if anvil.server.context.background_task_id is not None:
        # Update progress state periodically (e.g., every 10 rows) or on last record
        if row_nr % 10 == 0 or row_nr == total_rows:
          pct = int((row_nr / total_rows) * 100) if total_rows else 0
          anvil.server.task_state['progress'] = pct
          progress_msg = f"Processed {row_nr} of {total_rows} rows"
          anvil.server.task_state['status'] = progress_msg
          # add message to logs state of background task
          current_logs = anvil.server.task_state.get('logs', [])
          # Extend master list with buffered messages
          current_logs.extend(log_buffer)
          # Update task_state logs and clear local buffer
          anvil.server.task_state['logs'] = current_logs
          message = ""
          log_buffer.clear()
          #logmsg("DEBUG", f"Added messages to logbuffer upto row {row_nr}")

  return message

# ------------------------
# Anvil callable functions  
# ------------------------ 

@anvil.server.callable
def client_globals():
  # 
  # Return client configuration variables values CONFIG["CLIENT"] back to Client
  #
  logmsg("DEBUG",CONFIG["CLIENT"])
  return CONFIG["CLIENT"]

@anvil.server.callable
def user_authentication():
  #
  # This function logs the Login connection from the client and return source ip address of connection
  # It can be enlarged for further authentication featues
  #
  # check database connection, and auto-reconnect if needed
  #
  conn.ping(reconnect=True)
  #
  user = anvil.users.get_user()
  ip_address = str(anvil.server.context.client.ip)
  msg = "Login connection from " + ip_address + ", User " + str(user['email'])
  
  logmsg("INFO",msg)
  return ip_address

@anvil.server.callable
def user_authorisation(site_id,user_initials):
  #
  # This function checks the rle of the user in the siteuserrole table and returns the site_role
  #

  global Global_site_role
  # check database connection, and auto-reconnect if needed
  conn.ping(reconnect=True)
  #
  with conn.cursor() as cur:
    query = f"SELECT Role FROM siteuserrole WHERE SiteId = %s AND UserShortId = %s AND Enabled = 'True'"
    logmsg("INFO",query)
    cur.execute(query,(str(site_id),str(user_initials)))
    result = cur.fetchall()
    if cur.rowcount != 0:
      Global_site_role = result[0]["Role"]
      msg = "Found user " + str(user_initials) + " in site " + str(site_id) + " with role as " + str(Global_site_role)
    else:
      msg = "No role found for user " + str(user_initials) + " in site " + str(site_id)
      Global_site_role = "unknown"
    logmsg("INFO",msg)
  return Global_site_role

@anvil.server.callable
def user_logout_notification(ip_address,email):
  #
  # This function logs the logout of a user 
  #

  msg = "Logout notification from " + str(ip_address) + ", User " + str(email)
  logmsg("INFO",msg)
  return

@anvil.server.callable
def create_csv(data_list,col_order,csv_name):
  #
  # This function create a csv file from the given data_list in the order given in col_order
  #

  # create the column order list from col_order
  if col_order is not None:
    col_list = sorted(list(col_order[0].keys()),key=lambda x: col_order[0][x])
  
  # check if data_list is empty
  if len(data_list) == 0:
    # data_list is empty so need to create at least a empty data_list with Columns Headings
    data = {}
    for column_name in col_list:
      data[column_name] = None
    data_list = [data]
  
  # Create Pandas DataFrame
  df_tmp = pd.DataFrame(data_list) 

  # 1. Define the specific column names to exclude
  specific_cols_to_drop = {"DBAcontrol", "select"}

  # 2. Collect all columns to drop in one single list comprehension / loop
  cols_to_drop = [
    col
    for col in df_tmp.columns
      if col.endswith(RT_EXTENSION) or col in specific_cols_to_drop
  ]

  # 3. Drop the identified columns from the DataFrame
  df_export = df_tmp.drop(columns=cols_to_drop)

  # delete unused dataframe
  del df_tmp
  
  # remove cols_to_drop (specific and 'Rtf) from the column list
  filtered_list = [
    col
    for col in col_list
      if not col.endswith(RT_EXTENSION) and col not in specific_cols_to_drop
  ]

  # re-order Pandas dataFrame with requested filtered column order
  if col_order is not None:
    df = df_export[filtered_list]
  else:
    df = df_export

  # delete unused dataframe
  del df_export

  # Automatically converts to the best possible types
  #logmsg("DEBUG",df.dtypes)
  df = df.convert_dtypes()
  
  # convert pandas dataframe to string (cannot send all datatypes to client so best to make all of type string)
  # pdf_result = pdf_result.mask(pdf_result.astype(str).eq('None') & df.isna(), '')
  df = df.astype('str')
      
  # make all None values empty string (otherwise they will be sent to client as 'None' string, which is not good for client side processing)
  df.replace(to_replace='None', value='',inplace=True)
  df.replace(to_replace='<NA>', value='',inplace=True)
  
  # 2. Get the CSV content as a string
  # Use .encode('utf-8') to convert the string to bytes, which BlobMedia requires
  csv_bytes = df.to_csv(index=False).encode('utf-8')
  
  # delete unused dataframe
  del df

  # Perform garbage collection
  gc.collect()

  # 3. Create the Anvil Media Object
  # - 'text/csv' is the MIME type for a CSV file.
  # - csv_bytes is the content.
  # - name is the suggested filename for the download.
  if csv_name == "":
    csv_name = "Anchurus_list_form_export.csv"
  csv_file = anvil.BlobMedia(
    'text/csv', 
    csv_bytes, 
    name = csv_name
  ) 
  return csv_file

# This function is commented out; maybe can be resurracted when we decide to implement print_form again
#@anvil.server.callable
#def print_form(form,site_id,table_name,action,data_list,page_info):
  # 1. Call PdfRenderer
  # - set name of exported csv file
  # - set page orientation and size
  # ****** Add more variables for user to select (quality, scale, margins) as well as landscape and paper size)
  # ****** need to add the column filter (set in the client) to the table before printing
  # - user render_form method for requested from and site_id
  #print("In print form")
  #print(site_id, table_name, action)
  #print(data_list)
#  pdf_form = PdfRenderer(filename='Anchurus_list_form.pdf',landscape=True,page_size='A3').render_form(form,site_id,table_name,data_list,action,page_info)
#  pdf_form = PDFRenderer(filename='Anchurus_list_form.pdf',landscape=True,page_size='A3').render_form(form,site_id,table_name,data_list,action,page_info)
#  return pdf_form

@anvil.server.callable
def get_saved_workareas(name):
  # 
  # This function returns the saved workareas for the current active user
  #
  user = anvil.users.get_user()
  # search for a saved_workarea with this name
  rows = app_tables.saved_workareas.search(q.all_of(name=name,email=user["email"]))
  return rows

@anvil.server.callable
def clear_saved_workareas(name):
  # 
  # This function clears the saved workareas for the current active user
  #
  user = anvil.users.get_user()
  # search for a saved_workarea with this name and user and delete the row(s)
  rows = app_tables.saved_workareas.search(q.all_of(name=name,email=user["email"]))
  for row in rows:
    row.delete()
  msg = "Cleared the saved workareas environment for " + name
  return msg

@anvil.server.callable
def save_workareas(name,work_areas_dict,site_id):
  # 
  # This function saves the workareas (in the work_areas_dict) for the given site_id for the current active user
  #
  date_time = datetime.now(timezone.utc)
  user = anvil.users.get_user()
  logmsg("DEBUG","Saving workareas for: "+name)

  # first delete current saved work_areas for this name and user
  rows = app_tables.saved_workareas.search(q.all_of(name=name,email=user["email"]))
  for row in rows:
    row.delete()
  
  # now save the new list of work_areas
  msg = ""
  try:
    app_tables.saved_workareas.add_row(name=name,
                                      datetime=date_time,
                                      email=user["email"],
                                      site=site_id,
                                      workarea_dict=work_areas_dict)
    msg = msg + "OK: Successfully saved workareas for: " + name + "\n"
    logmsg("INFO",msg)
  except Exception as e:
    msg = msg + "ERROR: Error saving workarea for: " + name + ". " + str(e) + "\n"
    logmsg("ERROR",str(e))

  return msg

@anvil.server.callable
def send_email(subject,body,recipient,reply_to=None):
  #
  # This function sends an email given subject, body and recipient
  #
  # check the from_address to use defined in the configuration file
  from_address = dict_get(CONFIG,["EMAIL","email_from_address"],default="no-reply@berksarch.co.uk") 

  if reply_to is None:
    # if reply_to not given, use the from address in the configuration file as the reply_to address.
    reply_to = from_address

  # 1. Create the message container
  msg = EmailMessage()
  msg.set_content(body)
  msg['Subject'] = subject
  msg['From'] = from_address
  msg['To'] = recipient
  msg["Reply-To"] = reply_to

  # Connect to the local Postfix server listening on TCP/IP port 25
  try:
    with smtplib.SMTP('localhost', 25) as server:
      # No login usually required for local relay, 
      # but you can add server.login() if configured.
      server.send_message(msg)

  except Exception as e:
    logmsg("ERROR",f"{e}")

  msg = "Sent email to " + recipient + ". Subj: " + subject + ". From: " + from_address
  logmsg("DEBUG",msg)
    
  return 

# ---------------------------------
# functions related to user actions
# ---------------------------------

@anvil.server.callable
def update_user_last_seen():
  #
  # This function updates the online_count by checking the users app_tables for active users in last delta_time minutes 
  #

  user = anvil.users.get_user()
  # set delta_time to 5 minutes
  delta_time = ONLINE_DELTA_TIME
  # Use timezone-aware UTC datetime
  now = datetime.now(timezone.utc)
  if user:
    user["last_seen"] = now
    msg = "Updated last_seen timestamp " + str(now) + " for user " + user["initials"]
    logmsg("DEBUG",msg)
  
  # 2. Count users active in the last 5 minutes
  five_mins_ago = now - timedelta(minutes=delta_time)
  online_count = len(app_tables.users.search(
                                             last_seen=q.greater_than(five_mins_ago)
                                            )
                    )
  return online_count

@anvil.server.callable
def system_users_get(type):
  #
  # This function give a list of users (type = online; list only active users in last delta_time minutes, otherwise list all users)
  #

  if type == "online":
    # Subtract delta_time minutes using UTC
    delta_time = ONLINE_DELTA_TIME
    five_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=delta_time)

    tmp_list = app_tables.users.search(last_seen=q.greater_than(five_mins_ago))
  else:
    tmp_list = app_tables.users.search()

  list = sorted(tmp_list, key=lambda x: (
                                         # 1. Primary Sort: Case-insensitive Last Name
                                         (x['lastname'] or "").casefold(),
                                         # 2. Tie Breaker: Lowercase 'lastname' comes BEFORE Uppercase 'lastname'
                                         not (x['lastname'] or "a").islower(),
                                         # 3. Secondary Sort: Case-insensitive Initials
                                         (x['initials'] or "").casefold(),
                                         # 4. Tie Breaker: Lowercase 'initials' comes BEFORE Uppercase 'initials'
                                         not (x['initials'] or "a").islower()
                                        ))
  #logmsg("DEBUG",list)
  msg = "Returned user list to client (" + str(len(list)) + " users)"
  # = "Returned user list to client ( users)"
  logmsg("INFO",msg)
  return list

@anvil.server.callable
def check_initials(initials_string):
  #
  # This function checks if the initials_string exists
  #
  list = app_tables.users.get(initials=initials_string)
  msg = "OK: no user found with initials " + initials_string
  if list != None:
    msg = "ERROR: user with initials " + initials_string + " already exits."
  logmsg("DEBUG",msg)
  return msg

@anvil.server.callable  
def system_user_update(user,systemrole,status,initials,firstname,lastname):
  #
  # This function updated the user records with the giben new values
  #
  row = app_tables.users.get(email = user)
  # check that there is always one enabled System Administrator user
  if row["systemrole"] == "System Administrator" and row["enabled"] == True and (status == False or systemrole != "System Administrator"): 
    # need to check if there is another enabled System Administrator user
    admin_users = app_tables.users.search(systemrole = "System Administrator", enabled = True)
    if len(admin_users) == 1:
      msg = "ERROR: Cannot disable the only enabled System Administrator user: " + admin_users[0]["email"]
      logmsg("ERROR", msg)
      return msg

  # update relevant fields (not password!)
  row.update(systemrole = systemrole, enabled = status, initials = initials, firstname = firstname, lastname = lastname)
  #print(dict(row))
  msg = "OK: Updated system user: " + str(user) + ", " + str(systemrole) + ", " + str(status) + ", " + str(initials)
  logmsg("INFO", msg)
  return msg

@anvil.server.callable  
def system_user_insert(email,password,systemrole,status,initials,firstname,lastname):
  #
  # This funtion will insert a new system user in the Anvil users DB table
  #

  # validate fields:
  email = email.strip().lower()
  # the current user must be an admin_user 
  admin_user = anvil.users.get_user()
  is_valid, msg = check_email(email)
  if is_valid:
    # only if check_email returns True, add the user to the table
    try:
      new_user = anvil.users.signup_with_email(email,password)
      #
      system_user_update(email,systemrole,status,initials,firstname,lastname)
      msg = ("\nDear %s,\n\n"
           "Welcome to Anchurus II.\n\n"
           "This is to notify you that you have been registered for access to the Anchurus-II system for %s\n\n"
           "To access this system click on %s\n"
           "Your login credentials are:\n"
           "Email: %s\n"
           "Password: %s\n\n"
           "This will take you to the Anchurus II control page. To learn what you can do next, click on Help which takes you to the Anchurus website.\n"
           "Click on the Anchurus II User Manual link and scroll down to the entry 'Using the Anchurus II web application: the basics – a site viewer’s view'\n\n"
           "This explains what to do next, including changing your password.\n\n"
           "Lookout for your next email from Anchurus II which explain which sites you can access.\n\n"
           "Best wishes,\n\n"
           "%s %s - %s\n\n"
           % (firstname,Global_organisation,anvil.server.get_app_origin(),email,password,admin_user["firstname"],admin_user["lastname"],admin_user["email"]))
      subject = ("Registration Anchurus-II system for %s" % (Global_organisation))
      anvil.server.call("send_email",subject,msg,email,admin_user["email"])
      msg = f"OK. Successfully registered systemuser {email}"
      logmsg("INFO", msg)
    except Exception as e:
      msg = "ERROR: An error occurred during registration of systemuser " + email + ": " + str(e)
      logmsg("ERROR", msg)
  else:
    logmsg("ERROR", f'Email check for systemuser {email} failed: {msg}')
  return msg

@anvil.server.callable
def system_user_delete(user_email):
  #
  # This funtion will delete a user form the Anvil users DB table
  #

  row = app_tables.users.get(email = user_email)

  # check that there is always one enabled System Administrator user
  if row["systemrole"] == "System Administrator" and row["enabled"] == True:
     # need to check if there is another enabled System Administrator user
     admin_users = app_tables.users.search(systemrole = "System Administrator", enabled = True)
     if len(admin_users) == 1:
        msg = "ERROR: Cannot delete the only enabled System Administrator user: " + admin_users[0]["email"]
        logmsg("ERROR", msg)
        return msg
  # delete the user
  msg = "SUCCESS: Deleted system user: " + str(user_email) 
  row.delete()
  logmsg("INFO", msg)
  return msg

# --------------------------------------------------
# <nam>_get functions (for listing, dropdowns, etc.)
# --------------------------------------------------
@anvil.server.callable
def execute_sql_command(sql_cmd):
  #
  # This funtion will execute a given SQL command.
  # It returns msg, pd_list, col_order, table_info
  #
  #
  table_info = []
  col_order = {}
  pd_list = []
  col_names = []
  msg = ""
  logmsg("DEBUG",f"SQL command to execute is {sql_cmd}")
  # only execute if the sql_cmd is safe 
  if is_safe_sql(sql_cmd):
    conn.ping(reconnect=True)
    # add "CREATE TEMPORARY TABLE temp_results AS " to sql_cmd
    clean_sql = sqlparse.format(sql_cmd, strip_comments=True).strip()
    parsed = sqlparse.parse(clean_sql)
    first_token = next(
        (t for t in parsed[0].tokens if not t.is_whitespace and t.ttype is not sqlparse.tokens.Comment), 
        None
    )
    verb = first_token.value.upper() if first_token else ""
    tmp_table_name = "temp_results_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if verb in ["SELECT"]:
      sql_cmd = "CREATE TEMPORARY TABLE " + tmp_table_name + " AS\n" + sql_cmd

    with conn.cursor() as cur:
      try:
        logmsg("DEBUG",sql_cmd)
        cur.execute(sql_cmd)
        result = cur.fetchall()
        #logmsg("DEBUG",result)
        result_description = cur.description
        logmsg("DEBUG",result_description)
        # add cmd to show temp table results
        # note that "SELECT" sql_cmd has changed to start with "CREATE"
        if sql_cmd[0:6] == "CREATE":
          sql_cmd = f"SELECT * FROM `{tmp_table_name}`;"
          logmsg("DEBUG",sql_cmd)
          cur.execute(sql_cmd)
          result = cur.fetchall()

        # put query result in pandas dataframe
        pdf_result = pd.DataFrame(result) 

        # Automatically converts to the best possible types
        pdf_result = pdf_result.convert_dtypes()
      
        # 1. Identify numeric columns (int and float) - replace NaN with 0
        num_cols = pdf_result.select_dtypes(include=['number']).columns
        pdf_result[num_cols] = pdf_result[num_cols].fillna(0)

        # 2. Identify object/string columns - replace NaN with empty string
        obj_cols = pdf_result.select_dtypes(exclude=['number']).columns
        pdf_result[obj_cols] = pdf_result[obj_cols].fillna('')

        # convert date yyyy-mm-dd to dd-mm-yyyy for display purposes
        converted_pdf = convert_date(pdf_result,'%d-%m-%Y')
      
        # convert pandas dataframe to string (cannot send all datatypes to client so best to make all of type string)
        pdf_result_str = converted_pdf.astype('str')

        # delete unused DataFrame
        del pdf_result
        del converted_pdf
        # Perform garbage collection
        gc.collect()
      
        # make all None values empty string (otherwise they will be sent to client as 'None' string, which is not good for client side processing)
        pdf_result_str.replace(to_replace='None', value='',inplace=True)
        pdf_result_str.replace(to_replace='<NA>', value='',inplace=True)
        #pdf_result_str.replace(to_replace='nan', value='',inplace=True)    

        # now put dataframe into records
        pd_list = pdf_result_str.to_dict('records')

        msg = "Found " + str(len(result)) + " rows."

        msg = "SUCCESS: SQL command completed. " + msg
        logmsg("INFO",msg)

        if sql_cmd[0:4] == "CALL":
          # create table_info from result_description
          logmsg("DEBUG","Creating table_info from cursor (db) results description")
          for col in result_description:
            field_name = col[0]
            type_code = col[1]
            internal_size = col[3]
            precision = col[4]
            scale = col[5]
            null_ok = col[6]

            # Map Nullability
            null_val = "YES" if null_ok else "NO"

            # Map Type Code to MariaDB/MySQL string representations
            if type_code in (FIELD_TYPE.VAR_STRING, FIELD_TYPE.STRING):  # 253, 254
              char_length = internal_size // 4
              type_str = f"varchar({char_length})"
            elif type_code in (FIELD_TYPE.BLOB, FIELD_TYPE.TINY_BLOB):  # 252 (TEXT)
              type_str = "text"
            elif type_code in (
                               FIELD_TYPE.LONG,
                               FIELD_TYPE.SHORT,
                               FIELD_TYPE.TINY,
                              ):  # 3 (INT)
              type_str = f"int({internal_size})"
            elif type_code in (FIELD_TYPE.NEWDECIMAL, FIELD_TYPE.DECIMAL):  # 246
              # position 4 is precision (overall length), position 5 is scale (decimals)
              true_precision = precision - 2 if scale > 0 else precision - 1
              type_str = f"decimal({true_precision},{scale})"
            elif type_code == FIELD_TYPE.DATE:  # 10
              type_str = "date"
            elif type_code in (FIELD_TYPE.DATETIME, FIELD_TYPE.TIMESTAMP):  # 12, 7
              # Handles fractional seconds precision if present (e.g. datetime(3))
              type_str = f"datetime({scale})" if scale and scale > 0 else "datetime"
            elif type_code == FIELD_TYPE.TIME:  # 11
              type_str = f"time({scale})" if scale and scale > 0 else "time"
            else:
              type_str = "unknown"

            # Build the column record matching DESCRIBE table format
            table_info.append(
                    {
                     "Field": field_name,
                     "Type": type_str,
                     "Null": null_val,
                     "Key": "",
                     "Default": None,
                     "Extra": "",
                    }
                   )
        else:
          # get table info from temp table with query result
          logmsg("DEBUG","Creating table_info from temp_table description")
          sql_cmd = "DESCRIBE " + tmp_table_name + ";"
          cur.execute(sql_cmd)
          table_info = cur.fetchall()
        logmsg("INFO",table_info)

        # create column names list from pdf_result; if this is empty use table_info
        if pd_list == []:
          for item in table_info:
            logmsg("DEBUG",item)
            col_names.append(item["Field"])
        else:
          col_names = list(pdf_result_str.columns.values)

        # set order number for columns
        pos = 1
        for column in col_names:
          col_order[column] = pos
          pos = pos +1

      except pymysql.Error as err:
        result = format(err)
        msg = "FAIL: SQL command failed: " + result
        logmsg("ERROR", msg)
      
      # delete temporary table "DROP TEMPORARY TABLE IF EXISTS temp_results;"
      sql_cmd = "DROP TEMPORARY TABLE IF EXISTS " + tmp_table_name + ";"
      cur.execute(sql_cmd)
      logmsg("DEBUG",sql_cmd)
  else:
    msg = "FAIL: SQL command is unsafe/incorrect: " + sql_cmd
    logmsg("ERROR",msg)
  # return msg, pandas dataframe pd_list, column order and table_info
  return msg, pd_list, col_order, table_info

@anvil.server.callable
def db_get_summary(site_id):
  #
  # This function will return a summary information (e.g. record count, table meta data, etc.) of relevant database tables
  # Excluded tables are dbdiary, site amd siteuserrole
  #

  # check database connection, and auto-reconnect
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    query = "SELECT table_name,table_rows FROM information_schema.tables WHERE table_schema = '" + database_connect_info["db"] + "' AND table_type = 'BASE TABLE' ORDER BY table_name"
    logmsg("DEBUG",query)
    try:
      cur.execute(query)
      result = cur.fetchall()
      # format result in list
      list = []
      for item in result:
        #print(item)
        if item["table_name"] not in ["dbdiary","site","siteuserrole"] and item["table_name"].find("sys_") == -1:
          table_info = describe_table(item["table_name"])
          count = 0
          for column in table_info:
            if "SiteId" in column.values():
              tablename = item["table_name"]
              query = f"SELECT COUNT(*) FROM `{tablename}` WHERE SiteId = %s"
              #logmsg("DEBUG",(query,[site_id]))
              try:
                cur.execute(query,[site_id])
                res2 = cur.fetchall()
                count = res2[0].get("COUNT(*)")
              except Exception as e:
                logmsg("ERROR",f"{e}")
                count = 0
          list.append(item["table_name"] + " - " + str(count))
    except Exception as e:
      logmsg("ERROR",f"{e}")
    
    msg = "DB summary requested."
    logmsg("INFO",msg)
  return list

@anvil.server.callable
def db_table_comment(table_name):
  #
  # This function will return the comment information of a given DB table
  #

  # check database connection, and auto-reconnect
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    query = "SELECT TABLE_COMMENT FROM information_schema.tables WHERE table_schema = '" + database_connect_info["db"] + "' AND table_name = '" + table_name + "'"
    cur.execute(query)
    result = cur.fetchall()
    if len(result) > 0:
      comment = result[0].get("TABLE_COMMENT")
    else:
      comment = ""
    msg = "DB table comment requested for table " + table_name
    logmsg("INFO",msg)
  return comment

@anvil.server.callable
def sites_get_summary(email):
  # check database connection, and auto-reconnect
  conn.ping(reconnect=True)
  anviluser = anvil.users.get_user(email)
  with conn.cursor() as cur:
    if anviluser["systemrole"] == "System Administrator":
      query = "SELECT SiteId,SiteName FROM site ORDER BY site.SiteId" 
    else:
      query = "SELECT site.SiteId,site.SiteName FROM site,siteuserrole WHERE site.SiteId = siteuserrole.SiteId AND siteuserrole.UserShortId = '" + anviluser["initials"] + "' AND siteuserrole.Enabled = 'True' ORDER BY site.SiteId"
    cur.execute(query)
    result = cur.fetchall()
    msg = "Found " + str(len(result)) + " sites for user " + str(anviluser["email"]) + " " + str(anviluser["initials"])
    logmsg("INFO",msg)
  return result

@anvil.server.callable
def systems_get_summary():
  # retrieve the list of systems from the Anvil DB systems table and return to client
  systems_list = []
  for row in app_tables.systems.search():
    systems_list.append(row["systemname"])
  return systems_list

@anvil.server.callable
def sites_get():
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    query = "SELECT * FROM site ORDER BY SiteId"
    cur.execute(query)
    result = cur.fetchall()
    pdf_result = pd.DataFrame(result)   
    #logmsg("DEBUG",result)
    msg = query + ". Found " + str(len(result)) + " site rows."
    logmsg("INFO",msg)
    # convert pandas dataframe to sting (cannot send all datatypes to client so best to make all of type string)
    pdf_result_str = pdf_result.astype('str')

    # delete unused datframe
    del pdf_result

    # now dataframe into records
    pd_list = pdf_result_str.to_dict('records')

    # delete unused dataframe
    del pdf_result_str
    gb.collect()
  return pd_list

@anvil.server.callable
def areas_get_summary(site_id):
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    cur.execute("SELECT AreaId FROM area WHERE SiteId = %s ORDER BY AreaId",site_id)
    result = cur.fetchall()
    msg = "Found " + str(len(result)) + " Area rows."
    logmsg("INFO",msg)
  return result

@anvil.server.callable
def areas_get(site_id):
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    cur.execute("SELECT * FROM area WHERE SiteId = %s ORDER BY AreaId",site_id)
    result = cur.fetchall()
    msg = "Found " + str(len(result)) +" Area rows."
    logmsg("INFO",msg)
  return result

@anvil.server.callable
def contexts_get_summary(site_id):
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    cur.execute("SELECT ContextId FROM context WHERE SiteId = %s ORDER BY ContextId",site_id)
    result = cur.fetchall()
    msg = "Found " + str(len(result)) +" Context rows."
    logmsg("INFO",msg)
  return result

@anvil.server.callable
def describe_table(table_name):
  if table_name in ["users","online users"]:
    # Anvil users DB table
    anvil_columns = app_tables.users.list_columns()
    # Map Anvil internal types to standard MySQL column types
    type_mapping = {
        'string': 'varchar(255)',
        'number': 'double',
        'bool': 'tinyint(1)',
        'datetime': 'datetime',
        'date': 'date',
        'media': 'longblob',
        'simple_object': 'json',
        'live_object': 'bigint(20)',      # Single Link column
        'live_object_set': 'json'         # Multiple Links column
    }

    result = []

    # 2. Convert each Anvil column to INFORMATION_SCHEMA format
    for idx, col in enumerate(anvil_columns, start=1):
      col_name = col['name']
      col_type_raw = col['type']
        
      # Determine SQL column type representation
      sql_type = type_mapping.get(col_type_raw, col_type_raw)
        
      # Mark primary keys and foreign keys (links)
      is_pk = col_name in ['id', '_id', 'email']
      is_fk = col_type_raw in ['live_object', 'live_object_set']
        
      column_key = ""
      if is_pk:
        column_key = "PRI"
      elif is_fk:
        column_key = "MUL"

      # Character length for strings
      if col_type_raw == 'string':
        max_len = 64
      elif col_type_raw == "datetime":
        max_len = 32
      else:
        max_len = None
      if col_name == "initials":
        max_len = 8

      # Build schema record
      result.append({
            'COLUMN_NAME': col_name,
            'COLUMN_TYPE': sql_type,
            'COLUMN_KEY': column_key,
            'IS_NULLABLE': 'YES',  # Anvil Data Tables allow nulls on standard columns
            'COLUMN_DEFAULT': None,
            'CHARACTER_MAXIMUM_LENGTH': max_len,
            'COLUMN_COMMENT': f"Anvil type: {col_type_raw}",
            'ORDINAL_POSITION': idx
      })
  else:
    # MariaDB table
    #query = f"DESCRIBE `{table_name}`"
    query = ("SELECT COLUMN_NAME,COLUMN_TYPE,COLUMN_KEY,IS_NULLABLE,COLUMN_DEFAULT,CHARACTER_MAXIMUM_LENGTH,COLUMN_COMMENT,ORDINAL_POSITION FROM INFORMATION_SCHEMA.COLUMNS WHERE "
             "TABLE_SCHEMA = %s AND TABLE_NAME = %s;")
    
    conn.ping(reconnect=True)
    with conn.cursor() as cur:
      cur.execute(query,(database_connect_info["db"], table_name))
      result = cur.fetchall()
      #result.pop() # exclude last column, which should be DBAcontrol
      #msg = "Found " + str(len(result)) +" Area rows."
      #logmsg("INFO",msg)
  return result

@anvil.server.callable   
def table_get(site_id,table_name):
  # 
  # Description: returns all records of table table_name
  #
  col_order = {}
  tmp_pd_list = []
  pd_list = []
  # create WHERE clause if there is a SiteId field and
  # select Primary keys for order_list (exclude SiteId)
  if table_name in ["users","online users"]:
    # Anvil users DB table
    type = "online" if table_name == "online users" else "all"
    users_list = system_users_get(type)
    #tmp_pd_list = app_tables.users.search(tables.order_by("lastname",ascending=True),tables.order_by("initials",ascending=True))
    # use python sorted and str.casefold() method to make sure the sort is case-insensitive (anvil uses Postgress methos which is case-sensitive) 
    #tmp_pd_list = app_tables.users.search()

    #pd_list = sorted(tmp_pd_list, key=lambda x: (
    #                                         # 1. Primary Sort: Case-insensitive Last Name
    #                                     (x['lastname'] or "").casefold(),
    #                                     # 2. Tie Breaker: Lowercase 'lastname' comes BEFORE Uppercase 'lastname'
    #                                     not (x['lastname'] or "a").islower(),
    #                                     # 3. Secondary Sort: Case-insensitive Initials
    #                                     (x['initials'] or "").casefold(),
    #                                     # 4. Tie Breaker: Lowercase 'initials' comes BEFORE Uppercase 'initials'
    #                                     not (x['initials'] or "a").islower()
    #                                    ))
    # convert the found users_list to a clean list of dictionaries
    result = [dict(row) for row in users_list]
  else:
    # getting data from a DB table
    table_info = describe_table(table_name)
    #logmsg("DEBUG",table_info)
    order_list = ""
    where_clause = ""
    for column in table_info:
      if column["COLUMN_NAME"] == "SiteId" and table_name != "site":
        where_clause = " WHERE SiteId = '" + site_id + "'"
      elif column["COLUMN_KEY"] == "PRI":
        if len(order_list) > 0:
          order_list = order_list + ", " + column["COLUMN_NAME"]
        else:
          order_list = column["COLUMN_NAME"]
    if table_name == "dbdiary":
      order_list = order_list + " DESC"
    sql_cmd = f"SELECT * FROM `{table_name}` {where_clause} ORDER BY {order_list}"
    
    #conn.ping(reconnect=True)
    with conn.cursor() as cur:
      logmsg("DEBUG",sql_cmd)
      cur.execute(sql_cmd)
      result = cur.fetchall()
      
  # result is from users table or DB table
  # put query result in pandas dataframe
  pdf_result = pd.DataFrame(result) 
      
  # Automatically converts to the best possible types
  pdf_result = pdf_result.convert_dtypes()

  # convert of date fields of yyyy-mm-dd to dd-mm-yyyy
  converted_pdf = convert_date(pdf_result,'%d-%m-%Y')

  del pdf_result
  # start conversion of fields of yyyy-mm-dd to dd-mm-yyyy
  # 1. Identify true datetime64 pandas types (timestamps, datetime)
  #all_date_cols  = list(pdf_result.select_dtypes(include=['datetime64']).columns)
  
  # 2. Dynamically scan 'object' (text/mixed) columns for hidden database dates
  #for col in pdf_result.select_dtypes(include=['object']).columns:
  #  # Check if the column is a string type and make it lowercase
  #  col_str = str(col).lower()
  #      
  #  # CRITICAL SAFETY: Skip any column ending in Rtf or Txt, or if it is empty
  #  if col_str.endswith(ALLOWED_EXTENSIONS) or pdf_result[col].dropna().empty:
  #    continue
  #  
  #  # Sample the first (5) few non-null rows to see if they look like dates
  #  sample_series = pd.to_datetime(pdf_result[col].dropna().head(5), errors='coerce')
  #      
  #  # If the sample converts cleanly to datetimes, add it to our list
  #  if not sample_series.isna().all():
  #    all_date_cols.append(col)
  #
  # 3. Apply the dd-mm-yyyy string formatting globally
  #for col in all_date_cols:
  #  pdf_result[col] = pd.to_datetime(pdf_result[col], errors='coerce').dt.strftime('%d-%m-%Y')
  #  # Clean up any NaT (Not a Time) missing data markers for Anvil
  #  pdf_result[col] = pdf_result[col].fillna('')
   
  # end of conversion of yyyy-mm-dd to dd-mm-yyyy fields
    
  # 1. Identify numeric columns (int and float) 
  #num_cols = pdf_result.select_dtypes(include=['number']).columns
  #pdf_result[num_cols] = pdf_result[num_cols].fillna('')

  # 2. Identify object/string columns - replace NaN with empty string
  #obj_cols = pdf_result.select_dtypes(exclude=['number']).columns
  #pdf_result[obj_cols] = pdf_result[obj_cols].fillna('')
      
  # convert pandas dataframe to string (cannot send all datatypes to client so best to make all of type string)
  # make all None/NaN/nan values an empty string
  pdf_result_str = converted_pdf.astype(str).mask(converted_pdf.isna(), "") 

  del converted_pdf
  gc.collect()

  # now make dataframe into records  
  pd_list = pdf_result_str.to_dict('records')
 
  #logmsg("DEBUG",pd_list)
  
  msg = "Found " + str(len(result)) + " " + table_name + " rows."
  logmsg("INFO",msg)
  
  col_names = list(pdf_result_str.columns.values)
  logmsg("DEBUG",col_names)

  pos = 1
  for column in col_names:
    col_order[column] = pos
    pos = pos +1
  logmsg("DEBUG",col_order)
  #logmsg("DEBUG",pd_list)
  return pd_list, col_order

@anvil.server.callable
def contexts_get(site_id):
  anviluser = anvil.users.get_user()

  logmsg("INFO","Function get contexts called for site " + site_id)
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    cur.execute("SELECT * FROM context WHERE SiteId = %s ORDER BY ContextId",[site_id])
    # ContextId,AreaId,ContextName,ContextType,FieldDescription
    result = cur.fetchall()
    msg = "Found " + str(len(result)) + " Context rows."
    logmsg("INFO",msg)
  return result

@anvil.server.callable   
def finds_get(site_id):
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    cur.execute("SELECT * FROM find WHERE SiteId = %s ORDER BY FindId",[site_id])
    result = cur.fetchall()
    msg = "Found " + str(len(result)) +" Find rows."
    logmsg("INFO",msg)
  return result

@anvil.server.callable
def site_get_information(site_id):
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    site_information = {}
    # get site information 
    #cur.execute("SELECT * FROM area WHERE SiteId = %s",[site_id])
    #count_areas = cur.rowcount
    cur.execute("SELECT * FROM context WHERE SiteId = %s",[site_id])
    count_contexts = cur.rowcount
    cur.execute("SELECT * FROM find WHERE SiteId = %s",[site_id])
    count_finds = cur.rowcount
    site_information = {"Contexts": count_contexts, "Finds": count_finds}
    msg = "Site summary for " + site_id + " #Contexts: " + str(count_contexts) + " #Finds: " + str(count_finds)
    logmsg("INFO", msg)
  return site_information
    
@anvil.server.callable
def context_get_details(site_id,context_id):
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    # get context details
    cur.execute("SELECT * FROM context WHERE ContextId = %s AND SiteId = %s",(context_id,site_id))
    context = cur.fetchall()

  return context

@anvil.server.callable
def db_table_list():
  tables_to_hide = ["site","dbdiary","query","siteuserrole"]
  # also hide find table (i.e. findregister table) if find_table variable in configuration != YES 
  if dict_get(CONFIG,["CLIENT","find_table"],default="YES").upper() != "YES":
    tables_to_hide.append("find")
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    cur.execute("SHOW TABLES")
    table_list = cur.fetchall()
    table_names = []
    for item in table_list:
      key = "Tables_in_" + database_connect_info["db"]
      if item[key] not in tables_to_hide and item[key].rfind("sys_") == -1: 
        # do not add tables_to_hide
        table_names.append(item[key])
  return table_names

# ---------------------
# delete functions
# ---------------------
@anvil.server.callable
def delete_row(table_name,list_rows_to_delete,user,session_id=None):
  logmsg("DEBUG","Deleting rows in table "+table_name)
  if session_id == None:
    session_id = anvil.server.get_session_id()
  message = ""
  msg = ""
  if table_name == "users":
    for row in list_rows_to_delete:
      logmsg("DEBUG","Row user to delete: "+str(row))
      return_msg = system_user_delete(row["email"])
      msg = msg + return_msg + "\n"
    message = msg
  else:
    # add DBAcontrol record
    msg = "Delete a selected list of rows from Table " + table_name + "\n"
    #user = anvil.users.get_user()
    dbacontrol = check_DBAcontrol(user,"d",msg,session_id)
    #

    # loop through list_rows_to_delete

    for row in list_rows_to_delete:
      # contruct WHERE clause
      where_clause = ""
      for key in row:
        where_clause = where_clause + key + " = '" + row[key] + "' AND "

      # remember to rstrip(" AND ") the where_clause
      where_clause_final = where_clause.rstrip(" AND ")
      conn.ping(reconnect=True)
      with conn.cursor() as cur:
        # delete selected row
        sql_cmd = f"DELETE FROM `{table_name}` WHERE {where_clause_final}"
        logmsg("DEBUG",sql_cmd)
        try:
          ret = cur.execute(sql_cmd)
          conn.commit()
          msg = "Successfully deleted row: " + sql_cmd
          logmsg("INFO", msg)
          # if deleted record was for a specialist finds table also delete FindId from findsregister    
          if table_name.lower().startswith(database_connect_info["special_finds_table_prefix"]):
            findsreg_tablename = dict_get(CONFIG,["DATABASE","findsregister_tablename"],default="findsregister")
            sql_cmd = f"DELETE FROM `{findsreg_tablename}` WHERE FindId = %s"
            ret = cur.execute(sql_cmd, row["FindId"])
            conn.commit()
            msg2 = "Successfully deleted row: " + sql_cmd
            logmsg("INFO", msg2)
            msg = msg + "\n" + msg2
        except pymysql.Error as err:
          ret = format(err)
          msg = "Deletion of row failed: " + ret
          logmsg("ERROR", msg)
        message = message + msg + "\n"
  return message

@anvil.server.callable
def delete_by_DBAcontrol(DBAcontrol,table_name):
  # add DBAcontrol record
  msg = "Delete rows from Table " + table_name + " where DBAcontrol = " + DBAcontrol
  user = anvil.users.get_user()
  session_id = anvil.server.get_session_id()
  dbacontrol = check_DBAcontrol(user,"d",msg,session_id)
  #
  conn.ping(reconnect=True)
  with conn.cursor() as cur:
    # delete all records from a table with this DBAcontrol
    sql_cmd = "DELETE FROM `" + table_name +"` WHERE DBAcontrol = '" + DBAcontrol + "'"
    logmsg("DEBUG",sql_cmd)
    try:
      ret = cur.execute(sql_cmd)
      conn.commit()
      msg = "Successfully deleted " + str(ret) + " rows: " + sql_cmd
      logmsg("INFO", msg)
    except pymysql.Error as err:
      ret = format(err)
      msg = "Deletion of rows failed: " + ret
      logmsg("ERROR", msg)
  return msg

# ---------------------
# <name>_update functions
# ---------------------
@anvil.server.callable
def row_update(site_id,table_name,items):
  if table_name == "users":
    # first convert enabled True or False string to a boolean
    if items["enabled"] == "True":
      items["enabled"] = True
    else:
      items["enabled"] = False
    message = system_user_update(items["email"],items["systemrole"],items["enabled"],items["initials"],items["firstname"],items["lastname"])
    message = "OK: " + message
    logmsg("DEBUG",message)
  else:
    # update row in DB table
    # add DBAcontrol field
    description = "Update row in table " + table_name
    user = anvil.users.get_user()
    items["DBAcontrol"] = check_DBAcontrol(user,"u",description,anvil.server.get_session_id())
    #logmsg("INFO",items)
    message = "OK"
    # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
    # put context_items dictionay into a pandas dataframe, i.e. a one row table
    table = pd.DataFrame(items,index=[1])
    #print(table)
    # insert table into database; first param is table name
    #print(table_name)
    #print(table)
    message = table_update(site_id,table_name,table)
  return message

#@anvil.server.callable
#def site_update(site_items):
#  conn.ping(reconnect=True)
#  # add DBAcontrol field   
#  description = "Update row in table site"
#  user = anvil.users.get_user()
#  site_items["DBAcontrol"] = check_DBAcontrol(user,"u",description,anvil.server.get_session_id())
#  #logmsg("INFO",site_items)
#  message = "OK"
#  id = site_items["SiteId"]
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put context_items dictionay into a pandas dataframe
#  table = pd.DataFrame(site_items,index=[1])
#  table = table.drop('SiteId', axis=1)
#  type = "site"
#  #print(table)
#  table.replace({np.nan: None},inplace=True)
#  cols = ""
#  for i in table.columns.tolist():
#      cols = cols + i + " = %s,"
#  type_id = type.capitalize() + "Id"
#  cur = conn.cursor()
#  message = ""
#  msg = ""
#  # 
#  for i,row in table.iterrows():
#    sql_cmd = "UPDATE " + type.lower() + " SET " + cols[:-1] + " WHERE SiteId = %s "
#    #logmsg("DEBUG",sql_cmd)
#    values = tuple(row) + (id,)
#    #logmsg("DEBUG",values)
#    try:
#      ret = cur.execute(sql_cmd,values)
#      conn.commit()
#      msg = "OK. Table " + type[:-1] + " row " + id + " successfully inserted."
#      logmsg("INFO",msg)
#    except pymysql.Error as err:
#      msg = format(err)
#      msg = type[:-1] + " " + id + " insert to database failed: " + msg
#      logmsg("ERROR", msg)
#    message = message + msg + "\n"
#  #print(message)
#  return message

#@anvil.server.callable
#def area_update(area_items):
#  conn.ping(reconnect=True)
#  # add DBAcontrol field
#  description = "Update row in table area"
#  user = anvil.users.get_user()
#  area_items["DBAcontrol"] = check_DBAcontrol(user,"u",description,anvil.server.get_session_id())
#  #logmsg("INFO",site_items)
#  message = "OK"
#  id = area_items["AreaId"]
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put context_items dictionay into a pandas dataframe
#  table = pd.DataFrame(area_items,index=[1])
#  table = table.drop('AreaId', axis=1)
#  table = table.drop('SiteId', axis=1)
#  type = "area"
#  #print(table)
#  table.replace({np.nan: None},inplace=True)
#  cols = ""
#  for i in table.columns.tolist():
#      cols = cols + i + " = %s,"
#  type_id = type.capitalize() + "Id"
#  cur = conn.cursor()
#  message = ""
#  msg = ""
#  # 
#  for i,row in table.iterrows():
#    sql_cmd = "UPDATE " + type.lower() + " SET " + cols[:-1] + " WHERE areaId = %s "
#    #logmsg("DEBUG",sql_cmd)
#    values = tuple(row) + (id,)
#    #logmsg("DEBUG",values)
#    try:
#      ret = cur.execute(sql_cmd,values)
#      conn.commit()
#      msg = "OK. " + type[:-1] + " " + id + " successfully inserted."
#      logmsg("INFO",msg)
#    except pymysql.Error as err:
#      msg = format(err)
#      msg = type[:-1] + " " + id + " insert to database failed: " + msg
#      logmsg("ERROR", msg)
#    message = message + msg + "\n"
#  #print(message)
#  return message

#@anvil.server.callable
#def context_update(context_items):
#  conn.ping(reconnect=True)
#  # add DBAcontrol field   
#  description = "Update row in table context"
#  user = anvil.users.get_user()
#  context_items["DBAcontrol"] = check_DBAcontrol(user,"u",description,anvil.server.get_session_id())
#  #logmsg("INFO",context_items)
#  message = "OK"
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put context_items dictionay into a pandas dataframe
#  table = pd.DataFrame(context_items,index=[1])
#  #print(table)
#  table.replace({np.nan: None},inplace=True)
#  #print(table)
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is mikiter to 65535 chars
#  cols = "`,`".join([str(col) for col in list(context_items.keys())])
#  values = "`,`".join([str(col) for col in list(context_items.values())])
#  #logmsg("INFO",cols)
#  #logmsg("INFO",values)
#  sql_cmd = """UPDATE context SET Year = %s, AreaId = %s, Name = %s, ContextType = %s, RecordStatus = %s,
#               FillOf = %s, Description = %s, Interpretation = %s, YearStart = %s, YearEnd = %s, DatesAssignedBy = %s,
#               DBAcontrol = %s WHERE ContextId = %s AND SiteId = %s"""
#  row = (context_items["Year"],context_items["AreaId"],context_items["Name"],context_items["ContextType"],context_items["RecordStatus"],
#         context_items["FillOf"],context_items["Description"],context_items["Interpretation"],context_items["YearStart"],context_items["YearEnd"], context_items["DatesAssignedBy"],
#         context_items["DBAcontrol"],context_items["ContextId"],context_items["SiteId"])
#  #logmsg("INFO",sql_cmd)
#  #logmsg("INFO",row)
#  try:
#    cur = conn.cursor()
#    ret = cur.execute(sql_cmd,row)
#    conn.commit()
#    message = "OK"
#    msg = "Context " + context_items["ContextId"] + " successfully updated"
#    logmsg("INFO",msg)
#  except pymysql.Error as err:
#    message = format(err)
#    msg = "Context UPDATE to database failed: " + message
#    logmsg("ERROR", msg)
#  return message

#@anvil.server.callable
#def find_update(find_items):
#  conn.ping(reconnect=True)
#  # add DBAcontrol field   
#  description = "Update row in table find"
#  user = anvil.users.get_user()
#  find_items["DBAcontrol"] = check_DBAcontrol(user,"u",description,anvil.server.get_session_id())
#  #logmsg("INFO",find_items)
#  message = "OK"
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put find_items dictionay into a pandas dataframe
#  table = pd.DataFrame(find_items,index=[1])
#  #print(table)
#  table.replace({np.nan: None},inplace=True)
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is limited to 65535 chars
#  cols = "`,`".join([str(col) for col in list(find_items.keys())])
#  values = "`,`".join([str(col) for col in list(find_items.values())])
#  #logmsg("INFO",cols)
#  #logmsg("INFO",values)
#  sql_cmd = """UPDATE find SET ContextId = %s, MaterialType = %s, Pieces = %s, FieldDescription = %s, DBAcontrol = %s
#               WHERE FindId = %s AND SiteId = %s"""
#  row = (find_items["ContextId"],find_items["MaterialType"],find_items["Pieces"],find_items["FieldDescription"],find_items["DBAcontrol"],find_items["FindId"],find_items["SiteId"])
#  #logmsg("INFO",sql_cmd)
#  #logmsg("INFO",row)
#  try:
#    cur = conn.cursor()
#    ret = cur.execute(sql_cmd,row)
#    conn.commit()
#    message = "OK"
#    msg = "Find " + find_items["FindId"] + " successfully updated"
#    logmsg("INFO",msg)
#  except pymysql.Error as err:
#    message = format(err)
#    msg = "Find UPDATE to database failed: " + message
#    logmsg("ERROR", msg)
#  return message

# --------------------
# <name>_add / <name>_insert functions
# --------------------

@anvil.server.callable
def row_insert(site_id,table_name,items):
  # add DBAcontrol field
  description = "Insert new row in table " + table_name
  user = anvil.users.get_user()
  items["DBAcontrol"] = check_DBAcontrol(user,"i",description,anvil.server.get_session_id())

  # set default return message to "OK"
  message = "OK"

  # put items dictionay into a pandas dataframe, i.e. a one row table
  table = pd.DataFrame(items,index=[1])
 
  # insert table into database; first param is table name
  message = table_insert(site_id,table_name,table,user,anvil.server.get_session_id())
    
  # delete unused dataframe and perform garbage collection
  del table
  gc.collect()

  return message

#@anvil.server.callable
#def site_add(site_items):
#  # add DBAcontrol field   
#  description = "Insert new row in table site"
#  user = anvil.users.get_user()
#  site_items["DBAcontrol"] = check_DBAcontrol(user,"i",description,anvil.server.get_session_id())
# 
#  message = "OK"
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put context_items dictionay into a pandas dataframe, i.e. a one row table
#  table = pd.DataFrame(site_items,index=[1])
#  
#  message = table_insert("site",table,user,anvil.server.get_session_id())
#    
#  # delete unused dataframe and perform garbage collection
#  del table
#  gc.collect()
#
#  return message

#@anvil.server.callable
#def area_add(area_items):
#  # add DBAcontrol field
#  description = "Insert new row in table area"
#  user = anvil.users.get_user()
#  area_items["DBAcontrol"] = check_DBAcontrol(user,"i",description,anvil.server.get_session_id())
#
#  message = "OK"
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put context_items dictionay into a pandas dataframe, i.e. a one row table
#  table = pd.DataFrame(area_items,index=[1])
# 
#  message = table_insert("area",table,user,anvil.server.get_session_id())
#
#    
#  # delete unused dataframe and perform garbage collection
#  del table
#  gc.collect()
#
#  return message

#@anvil.server.callable
#def find_add(find_items):
#  # add DBAcontrol field
#  description = "Insert new row in table find"
#  user = anvil.users.get_user()
#  find_items["DBAcontrol"] = check_DBAcontrol(user,"i",description,anvil.server.get_session_id())
#
#  message = "OK"
#  
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put context_items dictionay into a pandas dataframe, i.e. a one row table
#  table = pd.DataFrame(find_items,index=[1])
#  
#  message = table_insert("find",table,user,anvil.server.get_session_id())
#    
#  # delete unused dataframe and perform garbage collection
#  del table
#  gc.collect()
#
#  return message

#@anvil.server.callable
#def context_add(context_items):
#  # add DBAcontrol field
#  description = "Insert new row in table context"
#  user = anvil.users.get_user()
#  context_items["DBAcontrol"] = check_DBAcontrol(user,"i",description,anvil.server.get_session_id())
#  
#  message = "OK"
#  # need to limit variables to limit of size of databae fields, e.g. FieldDescription is less than to 65535 chars
#  # put context_items dictionay into a pandas dataframe, i.e. a one row table
#  table = pd.DataFrame(context_items,index=[1])
# 
#  # insert tabke into database; first param is table name (plural lowercase)
#  message = table_insert("context",table,user,anvil.server.get_session_id())
#  
#  # delete unused dataframe and perform garbage collection
#  del table
#  gc.collect()
#
#  return message

# -----------------------
# Image upload functions
# ----------------------

@anvil.server.callable
def uplink_download(media_list):
  conn.ping(reconnect=True)
  # loop through list of media objects
  i = 1
  for file in media_list:
    file_extension = "." + file["File"].content_type.rsplit("/")[1]
    # get current date and time
    current_datetime = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    image_id = str(current_datetime) + str(i)
    # create a unique file name
    file_name = "./local/" + file["site"] + "-" + file["context"] + "-" + image_id + file_extension
    #file_name = "./local/" + file["site"] + "-" + file["context"] + "-" + uuid.uuid4().hex + file_extension
    with open(file_name,"wb") as f:
      f.write(file["File"].get_bytes())
    # Now insert media file details into DB Images Table
    sql_cmd = """INSERT INTO Images(ImageId, Caption, Copyright, ContentType, LocationURL, DBAcontrol, SiteId, ContextId, FindId)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    row = (image_id,file["caption_text"],file["copyright_text"],file["File"].content_type,file_name,"DBA1",file["site"],file["context"],file["find"])        
    msg = "Received file from client - stored at " + file_name
    try:
      cur = conn.cursor()
      cur.execute(sql_cmd,row)
      conn.commit()
      i = i + 1
      logmsg("INFO",msg)
    except pymysql.Error as err:
      message = format(err)
      msg = "Image " + file_name + " INSERT to database failed: " + message
      logmsg("ERROR", msg)
  # all done
  return

@anvil.server.callable
def images_get(site_id,context_id):
  # get images for this context
  #conn = connect()
  cur = conn.cursor()
  cur.execute("SELECT * FROM Images WHERE ContextId = %s AND SiteId = %s",(context_id,site_id))
  images = cur.fetchall()
  ret = []   # empty array for return rows
  for image in images:
    file = image["LocationURL"]
    #print(file)
    with open(file, 'rb') as f:
       ret.append({'image' : anvil.BlobMedia(image["ContentType"], f.read()),'Caption' : image["Caption"], 'Copyright' : image["Copyright"], 'ContentType' : image["ContentType"]})
    msg = "Sending file to client: " + file
    logmsg("INFO", msg)
  return ret

# --------------------
# DBAcontrol functions
# --------------------

@anvil.server.callable
def check_DBAcontrol(user,action,description,session_id):
  #
  # Description: Check DB for an existing DBAcontrol record or add a new DBAcontrol record.
  #              DBAcontrol value format is yyyymmddAIIS (where yyyy=year, mm=month, dd=day of month,A=action lowecase{b|r|e|u|i|d}, III=initials user,S=sequence Number {001|999}
  #              Seq_num will roll over back to 001 after reaching 999
  # Paramenters:
  #    user: user record of anvil.users.get()
  #    action: lowercase letter {b|r|e|u|i|d}
  #    description: description
  # Return: an existing or a new DBAcontrol value
  #
  DBA_action_dict = {"a": "ALTER", "b": "IMPORT", "r": "RELOAD", "e": "EDIT", "u": "UPDATE", "i": "INSERT", "d": "DELETE"}
  current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
  current_datetime = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
  #row = app_tables.users.get(email = user)
  user_initials = user["initials"]
  #session_id = anvil.server.get_session_id()
  DBAcontrol_search = current_date + action + user_initials  + "%"
  #conn = connect()
  cur = conn.cursor()
  # search for an existing DBAcontrol record using search criteria of 'today, action and initials' 
  sql_cmd = """SELECT * FROM dbdiary WHERE DBAcontrol LIKE %s ORDER BY DBAcontrol DESC LIMIT 1"""
  cur.execute(sql_cmd,DBAcontrol_search)
  records = cur.fetchall()
  # there should only be one row in the records returned !
  for row in records:
    DBAcontrol = row["DBAcontrol"]
    logmsg("DEBUG","Found DBAcontrol record: "+str(row))
  new_DBAcontrol = ""
  if not records:
    # no existing DBAcontrol record found so start at seq_no "001"
    new_DBAcontrol = current_date + action + user_initials + "001"
    logmsg("DEBUG",f"Not found DBAcontrol records. Creating new DBAControl:{new_DBAcontrol}")
  else:
    # DBAcontrol exist but need to create the next sequence number
    #if session_id != row["URL"] or action == 'b':
    # DBAcontrol exists but session_id is new, OR action is Bulk Upload/Import: create new DBAcontrol
    # find latest seq_no (last position of DBAcontrol) and use next letter (may need to extend to beyond lowercase z and continue with [A..Z])
    #print(DBAcontrol)
    str_num = DBAcontrol[12:15]
    next_num = (int(str_num) % 999) + 1
    new_DBAcontrol = current_date + action + user_initials + f"{next_num:03d}" # chr(ord(DBAcontrol[12])+1)
    #print("Found existing DBAcontrol, but anvil session is different, so creating new DBAcontrol",new_DBAcontrol)
  if new_DBAcontrol != "":
    # there is not an existing DBAcontrol record for the current session_id in the database so a new DBAcontrol record has to be added to database
    project = "TBD"
    schema = "TBD"
    sql_cmd = """INSERT INTO dbdiary(DBAcontrol, Activity, Project, URL, Description, CreationDt, Schema)
              VALUES (%s, %s, %s, %s, %s, %s, %s)"""
    email = user["email"]
    ip_address = str(anvil.server.context.client.ip)
    activity = "Web session from " + ip_address + ", User " + str(email) + ", " + current_datetime
    row = (new_DBAcontrol,DBA_action_dict[action],project,session_id,description,current_datetime,schema)        
    try:
      cur = conn.cursor()
      cur.execute(sql_cmd,row)
      conn.commit()
      msg = "Created new DBAcontrol record: " + new_DBAcontrol + " (session_id: " + session_id + ")"
      logmsg("INFO",msg)
      DBAcontrol = new_DBAcontrol
    except pymysql.Error as err:
      message = format(err)
      msg = "DBAcontrol " + new_DBAcontrol + " INSERT to database failed: " + message
      logmsg("ERROR", msg)
      DBAcontrol = ""
  else:
    # there is an existing record for this DBAcontrol, so just return this existing DBAcontrol value
    msg = "DBAcontrol: found existing DBAcontrol record: " + DBAcontrol
    logmsg("INFO",msg)
  # DBAcontrol now has the value of the exisiting or new record in the DB, so return this to caller. If the INSERT to database failed, the DBAcontrol value is empty string.
  return DBAcontrol
  

#
#
#

@anvil.server.background_task
@anvil.server.callable
def import_file_task(site_id, table_name, file, user, session_id):
  # add DBAcontrol field
  description = f"Import of file for table {table_name} in site {site_id}"
  #user = anvil.users.get_user()
  DBAcontrol = check_DBAcontrol(user,"b",description,session_id)
  # get file type
  if file.content_type and "/" in file.content_type:
    file_type = file.content_type.rsplit("/", 1)[1]
  elif file.name and "." in file.name:
    file_type = file.name.rsplit(".", 1)[1].lower()
  else:
    file_type = "bin"
  
  # 
  with anvil.media.TempFile(file) as tempfilename:
    msg = f"Receiving {table_name} import file from client and storing in temp file: {tempfilename}"
    logmsg("INFO", msg)
    
    # get table info
    table_info = describe_table(table_name)

    # get columns that are date fields
    list_db_table_date_columns = [
       table_info["COLUMN_NAME"]
       for col in table_info
         if col.get("COLUMNS_TYPE", "").lower() == "date"
    ]
    all_db_table_column_names = [col["COLUMN_NAME"] for col in table_info]

    # get current date_time
    registrationdate = datetime.now(timezone.utc)

    # read Import file as Pandas Dataframe
    try:
      table_read = False
      if file_type == "csv":
        # read .csv file
        table = pd.read_csv(tempfilename,dtype='str',encoding="cp1252")
        table_read = True
      elif file_type == "xlsx":
        # read .xlsx spread sheet an convert date fields to YYYY-MM-DD format
        table = pd.read_excel(tempfilename,dtype='str',dayfirst=True,parse_dates=list_db_table_date_columns)
        table_read = True
      else:
        # uknown/unsupported file type
        table_read = False
      
      if table_read:

        logmsg("DEBUG","read tempfile into pandas table")
        logmsg("DEBUG",table)

        # check columns in pandas table with columns in database table
        df_column_names = table.columns.tolist()
        # keep_default_na=False avoids auto-converting empty strings to NaN prematurely
        table = table.replace(r'(?i)^\s*n/a\s*$', '', regex=True)
        table.replace({np.nan: None},inplace=True)
        if table_name != "users":
          # add DBAcontrol column
          table["DBAcontrol"] = DBAcontrol
          logmsg("DEBUG","Added DBAcontrol column to pandas table")
          if table_name == "siteuserrole":
            # special case for siteuserrole table import: need to add RegistrationDate field
            table['RegistrationDate'] = registrationdate.strftime('%Y-%m-%d %H:%M:%S')
            # strip spaces and convert Email field to lowercase
            table["Email"] = table["Email"].str.strip().str.lower()
        
          # 1. Identify columns ending with TX_EXTENSION and copy content to corresponding RT_EXTENSION column
          txt_cols = [col for col in table.columns if col.endswith(TX_EXTENSION)]
          logmsg("DEBUG",f"Found txt_columns: {txt_cols}")
          tx_len = len(TX_EXTENSION)
          for col in txt_cols:
            source_col = col
            target_col = source_col.removesuffix(TX_EXTENSION) + RT_EXTENSION
            # Single-line Pandas trick to convert plain text into Quill Delta JSON string
            table[target_col] = table[source_col].apply(
               lambda x: (
                   json.dumps(
                         {"ops": [{"insert": str(x) if str(x).endswith("\n") else str(x) + "\n"}]}
                   )
                   if pd.notna(x)
                   else None
               )
            )

          # 2. convert date files so format is yyyy-mm-dd
          table_converted = convert_date(table,'%Y-%m-%d')


          logmsg("DEBUG","now ready to insert table")
          # now do the table_insert
          message = table_insert(site_id,table_name,table,user,session_id)

          nr_of_rows = len(table)
          # nr_of_rows = len(message.splitlines(False))
          # nr_of_ok = message.count("OK.")
          ret_msg = f"-- {str(nr_of_rows)} rows processed. Change ID: {DBAcontrol}\n"
          logmsg("INFO",ret_msg)
        else:
          # special case for Anvil system users table
          # strip spaces and convert email field to lowercase
          table["email"] = table["email"].str.strip().str.lower()
          ret_msg = ""
          msg = ""
          for i,row in table.iterrows():
            # validate systemrole field
            if row["systemrole"] in ["Site Administrator","Site User"]:
              msg = system_user_insert(row["email"],row["password"],row["systemrole"],True,row["initials"],row["firstname"],row["lastname"])
            else:
              msg = "ERROR: Invalid systemrole for user " + row["email"] + ": " + row["systemrole"]
            ret_msg = ret_msg + msg + "\n"
          logmsg("INFO",ret_msg)
      else:
        # uknown/unsupported filetype
        ret_msg = f"Unsupported file type {file_type} of import file for table {table_name}\n"
    except Exception as e:
      ret_msg = f"Error reading import file for table {table_name}. {str(e)}\n"
    return ret_msg


# Server-callable wrapper that launches the background task
@anvil.server.callable
def start_import_job(site_id,table_name, file):
  session_id = anvil.server.get_session_id()
  user = anvil.users.get_user()
  task = anvil.server.launch_background_task("import_file_task", site_id, table_name, file, user, session_id)
  return task

#
# Functions to handle log file compression
#
def namer(name):
    return name + ".gz"

def rotator(source, dest):
    with open(source, 'rb') as f_in:
        with gzip.open(dest, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(source)

def logmsg(level,message):
  # This function adds the Anvil session_id to the log message and logs the message to the log file with the specified log level
  if level == "INFO":
    logging.info("%s | %s",anvil.server.get_session_id(),message)
  elif level == "ERROR":
    logging.error("%s | %s",anvil.server.get_session_id(),message)
  elif level == "DEBUG":
    logging.debug("%s | %s",anvil.server.get_session_id(),message)
  elif level == "WARNING":
    logging.warning("%s | %s",anvil.server.get_session_id(),message)
  elif level == "CRITICAL":
    logging.critical("%s | %s",anvil.server.get_session_id(),message)
  return

#----------------------------------------------------------------------------------------#
# This is the start of the server code execution; the following lines are executed at
# startup of the server and before any calls from the client are processed
#----------------------------------------------------------------------------------------#

#----------------------------------------------------------------------------------------#
# The folling line has to be commented out / removed when deploying this as server code
# using the Anvil-app-server it connects direct to the Client
#----------------------------------------------------------------------------------------#

#
# server_LZGIBCZDR4NAHF2POW6HEQO7-DZDU5DXYD6WQRSDO
#
#anvil.server.connect("server_66Z2XPBNPYB7OPLH6YYIZ7CH-C2MDNQZTH5EUDPID") # to be commented out when running in Server Module

# Reading configuration.yaml file
configuration_file = os.getenv('ANVIL_APP_CONFIGURATION_FILE', 'anchurus.yaml')
with open(configuration_file, "r") as f:
    CONFIG = yaml.safe_load(f)

# Securely inject database password and admin password from bash environment into the CONFIG python dictionary
CONFIG["DATABASE"]["password"] = os.environ.get("DB_PASSWORD")
CONFIG["USERS"]["admin_pw"] = os.environ.get("ADMIN_PW")

# Build disctint dictionaries with CONFIG details.

sysinfo = {}
sysinfo["loglevel"] = dict_get(CONFIG,["DEFAULT","loglevel"],default="INFO").upper()
sysinfo["email_from_address"] = dict_get(CONFIG,["EMAIL","email_from_address"],default="no-reply@berksarch.co.uk")

database_connect_info = {}
database_connect_info["host"] = dict_get(CONFIG,["DATABASE","host"],default="localhost")
database_connect_info["port"] = dict_get(CONFIG,["DATABASE","port"],default="3306")
database_connect_info["user"] = dict_get(CONFIG,["DATABASE","user"],default="root")
database_connect_info["password"] = dict_get(CONFIG,["DATABASE","password"],default="toor")
database_connect_info["db"] = dict_get(CONFIG,["DATABASE","db"],default="mydb")
database_connect_info["special_finds_table_prefix"] = dict_get(CONFIG,["DATABASE","special_finds_table_prefix"],default="fs")

users_info = {}
users_info["admin_domain"] = dict_get(CONFIG,["USERS","admin_domain"])
users_info["admin_user"] = dict_get(CONFIG,["USERS","admin_user"])
users_info["admin_pw"] = dict_get(CONFIG,["USERS","admin_pw"])
users_info["admin_firstname"] = dict_get(CONFIG,["USERS","admin_firstname"])
users_info["admin_lastname"] = dict_get(CONFIG,["USERS","admin_lastname"])
users_info["admin_user_initials"] = dict_get(CONFIG,["USERS","admin_user_initials"])

client_info = {}
client_info["db_name"] = dict_get(CONFIG,["CLIENT","db_name"])
client_info["rows_per_page"] = dict_get(CONFIG,["CLIENT","rows_per_page"],default="10")
client_info["version"] = dict_get(CONFIG,["CLIENT","version"])
client_info["organisation"] = dict_get(CONFIG,["CLIENT","organisation"])
client_info["highlight_colour"] = dict_get(CONFIG,["CLIENT","highlight_colour"],default="#A9B2A3")
client_info["prefix_special_finds_table"] = dict_get(CONFIG,["CLIENT","prefix_special_finds_table"],default="fs")

dict_ensure_list_items(CONFIG, ["CLIENT","TextArea_columns"], ["SQL_command","Description"])

# make list of required table/columns that are TextArea TEXT fields (so no RT equivalent column)
dict_required_tabcols = {"query": ["SQL_command"], "dbdiary": ["Description"]}
dict_merge_nested_structure(CONFIG, ["CLIENT","TextArea_columns_new"],dict_required_tabcols)
logmsg("DEBUG",["CLIENT","TextArea_columns_new"])

# add users_info to client_info
client_info.update(users_info)
CONFIG["CLIENT"].update(users_info)

global Global_email_from_address
Global_email_from_address = sysinfo["email_from_address"]

global Global_admin_user
Global_admin_user = users_info["admin_user"]

global Global_organisation
Global_organisation = client_info["organisation"]

# -------------
# setup logging 
# -------------
log_path = os.getenv('ANVIL_APP_LOG_FILE', 'ANII-R2-server.log')
print("Logging to file: " + log_path)

# Convert string logging level to logging constant; default=logging.INFO
# This step ensures compatibility across all Python versions
numeric_loglevel = getattr(logging, sysinfo["loglevel"], logging.INFO)

# 1. Stop console logging (stdout/stderr)
# handlers=[] : This prevents logging from being sent to the default stderr handler; 
# instead we will use a TimedRotatingFileHandler to write logs to file with rotation at midnight and keep 7 days of logs
logging.basicConfig(level=numeric_loglevel,handlers=[],force=True)
root_logger = logging.getLogger('')

# 2. Setup TimedRotatingFileHandler with backupCount
file_handler = TimedRotatingFileHandler(
    filename=log_path, 
    when='midnight', 
    interval=1, 
)
# 3. Attach the compression functions to the handler so that when the log file is rotated at midnight, the old log file is compressed and saved with a .gz extension
file_handler.namer = namer
file_handler.rotator = rotator

# 4. Set format and add to logger
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

#root_logger.addHandler(file_handler)

#
# log startup message
#
logmsg("INFO","--------------------------")
logmsg("INFO","Anchurus-II server started")
logmsg("INFO","--------------------------")
logmsg("INFO","Logging to file: " + log_path)

web_app_details = "Web app client ID " + str(anvil.app.id)
logmsg("INFO",web_app_details)

# connect to database
try:
  conn = pymysql.connect(host=database_connect_info["host"],
                         port=int(database_connect_info["port"]),
                         user=database_connect_info["user"],
                         password=database_connect_info["password"],
                         db=database_connect_info["db"],
                         cursorclass=pymysql.cursors.DictCursor)
  msg = "Successfully connected to database: " + database_connect_info["db"]
  logmsg('INFO',msg)
except pymysql.Error as err:
  logmsg("ERROR",format(err))

#
# Check if an enabled admin_user is in Anvil users table; if not then create a new user (as defined in the configuration file)
# as admin_user in the Anvil user table. This is only run at startup and will ensure there is always one enabled admin user.
# There is also a check on deleting registered users to make sure one does not delete the only/last system administrator.
#
# First check it users table has the extra columns (initials, firstname, lastname, systemrole) added for the
# admin user management; if not then add these columns

#cols = app_tables.users.list_columns()
#logmsg('INFO',"Columns in users table: " + str(cols))   

#if "initials" not in cols:
#  app_tables.users.add_column("initials",str)
#  app_tables.users.add_column("firstname",str)
#  app_tables.users.add_column("lastname",str)
#  app_tables.users.add_column("systemrole",str)

# get the current list of users in Anvil users table (ordered by email) and 
# log this information; this is used for debugging and to check if the admin 
# user defined in the configuration file already exists in the Anvil users table
user_list = app_tables.users.search(tables.order_by("email"))

# get the list of 'enabled' System Administrator users
admin_users = app_tables.users.search(systemrole = "System Administrator", enabled = True)
if len(admin_users) > 0:
  msg = "Found System Administrator user(s): "
  for user_row in admin_users:
    msg = msg + str(user_row["email"]) + " "
else:
  # No enabled System Administrators found
  #
  # check if users_info["admin_user"] exists:
  admin_users = app_tables.users.search(email=users_info["admin_user"])
  if len(admin_users) > 0:
    # user exists but is not System Administrator or is disabled; so force update this user to be an enabled System Administrator
    msg = system_user_update(users_info["admin_user"],
                             "System Administrator",
                             True,
                             users_info["admin_user_initials"],
                             users_info["admin_firstname"], 
                             users_info["admin_lastname"]
                             )
  else:
    # create new System Administrator user
    msg = system_user_insert(users_info["admin_user"],
                             users_info["admin_pw"],
                             "System Administrator",
                             True,
                             users_info["admin_user_initials"],
                             users_info["admin_firstname"],
                             users_info["admin_lastname"]
                             )
    body = ("\nHi %s %s,"
            "\n\nThis is to notify that your email address %s has been configured as primary System Administrator for %s in the Anchurus-II Web Application with URL %s.\n\n"
            "kind regards\n\nThe Anchurus-II service"
            % (users_info["admin_firstname"],users_info["admin_lastname"],users_info["admin_user"],client_info["organisation"],anvil.server.get_app_origin()))
    anvil.server.call("send_email","Anchurus-II system administrator",body,users_info["admin_user"])
logmsg('INFO',msg)

#---------------------------------------------------------------------------------------#
# The folling line has to be commented out / removed when deploying this as server code
# using the Anvil-app-server con
#---------------------------------------------------------------------------------------#  
# Now wait for calls from frontend (browser)

#anvil.server.wait_forever() # to be commented out when running in Server Module

