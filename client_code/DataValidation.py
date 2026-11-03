import anvil.server
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
import anvil.users
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables

import re

# This is the DataValidation module.

def validate_email(email):
  pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
  if not email or not re.match(pattern, str(email).strip()):
    return False, "Invalid email address format."
  return True, ""

def validate_integer(number):
  # Convert number to string and clean whitespace
  num_str = "" if number is None else str(number).strip()
  #  Allow empty strings (valid for optional fields)
  if num_str == "":
    return True, ""
  pattern = r"^$|^\d*$"
  if not number or not re.match(pattern, str(number).strip()):
    return False, "Invalid whole number format."
  return True, ""

def validate_year(number):
  # Convert number to string and clean whitespace
  num_str = "" if number is None else str(number).strip()
  #  Allow empty strings (valid for optional fields)
  if num_str == "":
    return True, ""
  pattern = r"^$|^(-?[0-9]{1,10}|)$"
  if not number or not re.match(pattern, str(number).strip()):
    return False, "Invalid year format."
  return True, ""

def validate_percentage(number):
  # Convert number to string and clean whitespace
  num_str = "" if number is None else str(number).strip()
  #  Allow empty strings (valid for optional fields)
  if num_str == "":
    return True, ""
  pattern = r"^(100(\.0+)?|[1-9]?\d(\.\d+)?)$"
  if not number or not re.match(pattern, str(number).strip()):
    return False, "Invalid percentage format."
  return True, ""

def validate_decimal(number, data_type):
  data_type_lower = data_type.lower()
  
  # Convert number to string and clean whitespace
  num_str = "" if number is None else str(number).strip()
  #  Allow empty strings (valid for optional fields)
  if num_str == "":
    return True, ""
    
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
    return False, f"Invalid format for {data_type}."

  return False, "Unknown data type."

def validate_BNGRcentroid(coordinate_string):
  clean_coordinates = coordinate_string.strip()
  #  Allow empty strings (valid for optional fields)
  if clean_coordinates == "":
    return True, ""
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
  match = BNGR_PATTERN.match(clean_coordinates)

  if not match:
    return False, f"'{clean_coordinates}' is not a valid BNG centroid format." # Invalid layout or mismatched precision length

  gd = match.groupdict()
  grid_square = gd['GridSq'].upper()

  # Coalesce the capture groups to find which specific precision length matched
  easting = gd['E2'] or gd['E3'] or gd['E4'] or gd['E5']
  northing = gd['N2'] or gd['N3'] or gd['N4'] or gd['N5']
  details = {
    "gird_square": grid_square,
    "easting": easting,
    "northing": northing,
    "precision_meters": 10**(5 - len(easting)) * 10 # Calculates actual ground precision
  }
  return True, details