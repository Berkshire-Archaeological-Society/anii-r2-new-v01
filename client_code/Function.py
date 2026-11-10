from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
import anvil.server
import anvil.users
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
import json

import re

# Global Functions
from . import Global

from ListContexts import ListContexts
from ListFinds import ListFinds
from ListSites import ListSites
from ListAreas import ListAreas
from ListUsers import ListUsers
from TableList import TableList
from ContextForm import ContextForm
from FindForm import FindForm
from AreaForm import AreaForm
from RowForm import RowForm
from SiteForm import SiteForm
from UserForm import UserForm
from ImportForm import ImportForm
from Help import Help
from Draw import Draw
#from Workarea import Workarea

def create_work_space(type,data_list):
  #print("Work space to create is: ",type)
  page_info = {}
  table_name = type.split(" ")[1].lower()
  action = type.split(" ")[0].lower()
  Global.query_view = False
  if table_name in Global.view_queries:
    Global.query_view = True

  # First param of RowForm and TableList is site_id, but is blanked out. Only used by server print function
  # Make sure any List actions that are not using the TableList Form should be listed first
  #if type in ["List Users","List Online Users"]:
  if type in ["List Users"]:
    #work_space = ListUsers()
    work_space = TableList("","users",data_list,type,page_info)
  #
  elif type in ["List Online Users"]:
    work_space = TableList("","online users",data_list,type,page_info)
  #
  elif type == "Edit User" or type == "Insert User":
    work_space = UserForm()
  #
  elif action == "list":
    work_space = TableList("",table_name,data_list,type,page_info)
  #
  elif action == "import":
    work_space = ImportForm()
  #  
  elif action == "help":
    work_space = Help()  
  #
  elif action in ["add","insert"]:
    work_space = RowForm("",table_name,data_list,type,page_info)
  #
  elif action == "edit":
    work_space = RowForm("",table_name,data_list,type,page_info)
  #
  elif action == "view":
    #print(action, table_name, type)
    if type.lower() == "view online users":
      table_name = "users"
    work_space = RowForm("",table_name,data_list,type,page_info)

  #elif type == "Draw":
  #  work_space = Draw()
  #
  elif type in ["Help Introduction","Site Introduction"]:
    work_space = Help()
  else:
    msg = "Unknown workspace to create: " + type
    print(msg)
    work_space = "Unknown"
  return work_space

def delete_workspace(work_area_name):
  # remove work_area_name form and work_area_name button
  #print("clearing workarea : "+work_area_name)
  Global.work_area[work_area_name]["button"].remove_from_parent()
  Global.work_area[work_area_name]["form"].remove_from_parent()
  # now remove (pop) the work_area_name from lists
  Global.work_area.pop(work_area_name)
  # clear header and make it invisible
  #Global.header_work_area_name.text = ""
  #Global.header_work_area_type.text = ""
  #Global.header.visible = False
  Global.main_form.menu_bottom.visible = False
  return

def format_cell_text(text, max_chars=100):
  if not text:
   return ""

  # 1. Split into lines
  lines = text.splitlines()
  was_truncated = False

  # 2. Check for newline limit (Max 2 lines)
  # if first line is longer that half of max_chars then only take first line; otherwise take first two lines
  if len(lines[0]) > max_chars / 2:
    text_to_process = "\n".join(lines[:1])
  else:
    if len(lines) > 2:
      # Take the first two lines and mark as truncated
      # check length secnd line 
      if len(lines[1]) < max_chars / 2:
        text_to_process = "\n".join(lines[:2])
      else:
        text_to_process = lines[0] + "\n" + lines[1][:int(max_chars/2)]
      was_truncated = True
    else:
      text_to_process = "\n".join(lines)

  # 3. Check for character limit
  if len(text_to_process) > max_chars:
    # Slice it and mark as truncated
    text_to_process = text_to_process[:max_chars]
    was_truncated = True

  # 4. Apply a single ellipsis if EITHER limit was hit
  if was_truncated:
    # Strip trailing spaces/newlines so the '...' sits flush
    return text_to_process.rstrip() + "..."

  return text_to_process

def set_allowed_actions():
  # this function will set the buttons visible/invisible in the current workspace based on the access permissions on the user role for this site 
  #print("In set_allowed_actions")
  #print("Global.action: " + Global.action)
  #print("Global.current_work_area_name: " + Global.current_work_area_name)
  #print("Global.table_name: " + Global.table_name)
  #print("Global.site_user_role: " + Global.site_user_role)
  #print("Global.system_user_role: " + Global.system_user_role)
  #print("Permission: " + str(Global.role_access.get(Global.site_user_role, {}).get(Global.table_name, {}).get(Global.action.split(" ")[0], None)))
  return

def restore_workareas():
  # look for saved_workareas
  name = "Saved_areas " + Global.site_id
  rows = anvil.server.call("get_saved_workareas",name)
  for row in rows:
    for workarea in row["workarea_dict"].keys():
      #print("in restore_workares: "+row["workarea_dict"][workarea]["action"])
      Global.restore_workarea_name = workarea
      Global.table_items = row["workarea_dict"][workarea]["data_list"]
      #print (workarea)
      if row["workarea_dict"][workarea]["form_type"] == "RowForm":
        # set Global.table_items if the from_type == RowForm (View, Edit of a row) and data_list should have only one row
        Global.table_items = row["workarea_dict"][workarea]["data_list"][0]
        #print("In restore")
        #print(Global.table_items)
        #print("now calling create_new_work_area")
      if row["workarea_dict"][workarea].get("query_info") is not None:
        Global.query_info = row["workarea_dict"][workarea]["query_info"]
        #print("In restore: query_info is " + str(Global.query_info))
      if row["workarea_dict"][workarea].get("column_order") is not None:
        Global.column_order = row["workarea_dict"][workarea]["column_order"]
      if row["workarea_dict"][workarea].get("tmp_table_info") is not None:
        Global.tmp_table_info = row["workarea_dict"][workarea]["tmp_table_info"]  
        #print("In restore: tmp_table_info is " + str(Global.tmp_table_info))
      Global.main_form.create_new_work_area(row["workarea_dict"][workarea]["action"])
    Global.restore_workarea_name = ""
  return

def clean_quill_regex(html_content):
  if not html_content:
    return ""

  # Remove leading spaces after the opening <p> tag
  cleaned = re.sub(r'^(<p[^>]*>)\s+', r'\1', html_content, flags=re.IGNORECASE)

  # Remove trailing spaces before the closing </p> tag
  cleaned = re.sub(r'\s+(</p>)$', r'\1', cleaned, flags=re.IGNORECASE)

  # Remove leading/trailing empty paragraph tags (<p><br></p> or <p></p>)
  cleaned = re.sub(r'^(<p>\s*(<br/?>)?\s*</p>)+', '', cleaned, flags=re.IGNORECASE)
  cleaned = re.sub(r'(<p>\s*(<br/?>)?\s*</p>)+$', '', cleaned, flags=re.IGNORECASE)

  return cleaned.strip()

def dict_get(data, keys, default=None):
  """Recursively traverse dictionary keys, returning default if any key is missing or None."""
  for key in keys:
    if isinstance(data, dict):
      data = data.get(key)
    else:
      return default
    if data is None:
      return default
  return data

def _clean_js_proxy(obj):
  """Recursively converts JavaScript proxyobjects and proxylists into native Python dicts, lists, and primitives."""
  if obj is None:
    return None

    # 1. Check for JS Proxy Lists / Arrays or Python Lists/Tuples FIRST
    # (Exclude strings and dicts so they don't get iterated as lists)
  if (
    isinstance(obj, (list, tuple))
    or hasattr(obj, "append")
    or type(obj).__name__ == "proxylist"
  ):
    return [_clean_js_proxy(item) for item in obj]

    # 2. Check for JS Proxy Objects or Python Dicts
  elif isinstance(obj, dict) or hasattr(obj, "keys"):
    return {str(k): _clean_js_proxy(obj[k]) for k in obj.keys()}

    # 3. Return primitives (str, int, float, bool) directly
  return obj

def update_db_summary():
  db_summary = anvil.server.call("db_get_summary",Global.site_id)
  Global.main_form.site_summary.visible = True
  Global.main_form.site_summary.items = db_summary
  return

def convert_quill_to_python(quill_comp):
  try:
    raw_contents = quill_comp.getContents()

    # Step 1: Unwrap top-level Delta ops
    if hasattr(raw_contents, "ops"):
      raw_ops = raw_contents.ops
    elif isinstance(raw_contents, dict) and "ops" in raw_contents:
      raw_ops = raw_contents["ops"]
    else:
      raw_ops = raw_contents

      # Step 2: Recursively clean proxylist and proxyobject instances
    clean_ops = _clean_js_proxy(raw_ops)

    # Step 3: Ensure clean_ops is enclosed in a Python list
    if not isinstance(clean_ops, list):
      clean_ops = [clean_ops] if clean_ops else []

    py_delta = {"ops": clean_ops}

  except Exception as e:
    #print(f"Quill conversion fallback triggered: {e}")
    text_val = str(quill_comp.getText() or "")
    if not text_val.endswith("\n"):
      text_val += "\n"
    py_delta = {"ops": [{"insert": text_val}]}

  return json.dumps(py_delta)

def scroll_log_to_bottom(component):
  """Scrolls the log_box TextArea directly to the bottom."""
  try:
    if component is not None:
      # Get the underlying HTML DOM element of the TextArea
      dom_element = anvil.js.get_dom_node(component)

      # Set scroll position to the total scroll height
      dom_element.scrollTop = dom_element.scrollHeight
  except Exception:
    pass
  pass

def load_column_configurations(raw_config):
  """Parses YAML config into a structured dictionary with defaults."""
  #raw_config = yaml.safe_load(yaml_string) or {}
  processed_config = {}

  for table_name, columns in raw_config.items():
    processed_config[table_name] = {}
    for col_name, rules in columns.items():
      processed_config[table_name][col_name] = {
        "label": rules.get("label", col_name),
        "width": rules.get("width", 300),
        "type": rules.get("type"),  # dropdown | list | single_select | multi_select| etc.
        "options": rules.get("options", []),
        "allow_other": rules.get("allow_other", False),
        "placeholder": rules.get(
          "placeholder", f"Select or enter {col_name}"
        ),
        "error": rules.get(
          "error", f"Please provide a valid selection for {col_name}"
        ),
      }

  return processed_config

def create_custom_select_component(config):
  """Generates a ColumnPanel containing dynamic RadioButtons or CheckBoxes

    along with an optional 'Other' toggle and text input.
    """
  container = FlowPanel()
  options = config.get("options", [])
  allow_other = config.get("allow_other", False)
  is_multi = config.get("type") == "multi_select"
  group_name = f"grp_{config.get('name', 'select')}"

  ctrl = {
    "type": config.get("type"),
    "options_controls": [],
    "other_toggle": None,
    "other_input": None,
  }

  # Helper callback to trigger custom x-change event on container
  def notify_container_change(**e):
    container.raise_event("x-change")

  # Render standard predefined options
  for opt in options:
    if is_multi:
      cb = CheckBox(text=opt, value=opt)
      cb.add_event_handler("change", notify_container_change)
      container.add_component(cb)
      ctrl["options_controls"].append(cb)
    else:
      rb = RadioButton(group_name=group_name, text=opt, value=opt)
      rb.add_event_handler("change", notify_container_change)
      container.add_component(rb)
      ctrl["options_controls"].append(rb)

    # Render 'Other' toggle and text input
  if allow_other:
    other_txt = TextBox(
      placeholder="Please specify 'Other'...", visible=False
    )

    if is_multi:
      other_toggle = CheckBox(text="Other")

      def on_toggle_change(**e):
        other_txt.visible = other_toggle.checked
        if not other_toggle.checked:
          other_txt.text = ""
        notify_container_change()

    else:
      other_toggle = RadioButton(group_name=group_name, text="Other")

      def on_toggle_change(**e):
        other_txt.visible = other_toggle.selected
        if not other_toggle.selected:
          other_txt.text = ""
        notify_container_change()

          # Hide 'Other' text input when predefined options are selected
      for rb in ctrl["options_controls"]:

        def make_reset_handler(txt):
          return lambda **e: setattr(txt, "visible", False)

        rb.add_event_handler("change", make_reset_handler(other_txt))

    other_toggle.add_event_handler("change", on_toggle_change)
    other_txt.add_event_handler("change", notify_container_change)
    container.add_component(other_toggle)
    container.add_component(other_txt)
    ctrl["other_toggle"] = other_toggle
    ctrl["other_input"] = other_txt

  container.tag = ctrl
  return container

def validate_custom_select(container):
  """Validates selection state AND checks that 'Other' text is provided if selected.

    Returns (is_valid: bool, error_message: str)
    """
  ctrl = getattr(container, "tag", None)
  if not ctrl:
    return False, "Invalid field configuration"

  is_multi = ctrl["type"] == "multi_select"

  if is_multi:
    selected_any = any(cb.checked for cb in ctrl["options_controls"])
    other_checked = (
      ctrl["other_toggle"].checked if ctrl["other_toggle"] else False
    )

    if not (selected_any or other_checked):
      return False, "Please select at least one option"

    if other_checked and not ctrl["other_input"].text.strip():
      return False, "Please specify a value for 'Other'"

    return True, ""

  else:  # single_select
    selected_any = any(rb.selected for rb in ctrl["options_controls"])
    other_selected = (
      ctrl["other_toggle"].selected if ctrl["other_toggle"] else False
    )

    if not (selected_any or other_selected):
      return False, "Please select an option"

    if other_selected and not ctrl["other_input"].text.strip():
      return False, "Please specify a value for 'Other'"

    return True, ""