from ._anvil_designer import RowFormTemplate
from anvil import *
import anvil.server
import re
import datetime
import json 
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
import anvil.users
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
from anvil_extras.Quill import Quill
from anvil.js import get_dom_node

#from ..Validation import Validator
from ..validation import Validator
from .. import FunctionsB
from .. import Function
from .. import Global
from .. import DataValidation


class RowForm(RowFormTemplate):
  def input_change(self, **event_args):
    """This method is called when the text in this text box is edited"""
    sender = event_args["sender"]
    #print(sender)
    # column name is in placeholder of field or in tag (quill datatype)
    tag_val = getattr(sender, "tag", None)
    placeholder_val = getattr(sender, "placeholder", None)

    # 2. Extract string value (ComponentTag objects convert to str or can be checked as instance)
    if isinstance(tag_val, str) and tag_val.strip():
        column = tag_val
    elif isinstance(placeholder_val, str) and placeholder_val.strip():
        column = placeholder_val
    else:
        column = None
      
    if not column or column not in self.form_fields:
      return

    field_info = self.form_fields[column]

    # Safe retrieval of component reference (supports both "field" and "input" keys)
    field_ref = field_info.get("field") or field_info.get("input") or sender
    max_length = field_info.get("length", 65535)

    # Determine if field is required (* vs &nbsp)
    is_nullable = next(
        (
            item["IS_NULLABLE"]
            for item in Global.work_area[Global.current_work_area_name][
                "table_info"
            ]
            if item["COLUMN_NAME"] == column
         ),
         "YES",
    )

    col = "&nbsp" if is_nullable == "YES" else "*"
    col += f"<b>&nbsp{column}</b>"
    #col = "&nbsp" + "<b>&nbsp"+column+"</b>"
    #if next((item['IS_NULLABLE'] for item in Global.work_area[Global.current_work_area_name]["table_info"] if item['COLUMN_NAME'] == column),0) != "YES":
    #  # add * to column if field is required; i.e. IS_NULLABLE value for column is not YES
    #  col = "*" + "<b>&nbsp"+column+"</b>"

    # only do char count for TextBox and TextArea type fields
    sender_type = str(type(sender))
    #print(sender_type)
    if sender_type in ["<class 'anvil.TextBox'>","<class 'anvil.TextArea'>"]:
      text_val = field_ref.text or ""

      cur_len = len(text_val)
      self.form_fields[column][
                  "header"
              ].content = f"{col} ({cur_len}/{max_length}):"
      #self.form_fields[column]["header"].content = col + " (" + str(len(self.form_fields[column]["field"].text)) + "/" + str(self.form_fields[column]["length"]) + "):"
    elif sender_type == "<class 'anvil_extras.Quill.Quill'>":
      # getText() returns plain text content; strip trailing newline added by Quill
      raw_text = sender.getText() or ""
      if raw_text.endswith("\n"):
        raw_text = raw_text[:-1]
        
        cur_len = len(raw_text)
                  
        self.form_fields[column][
                  "header"
              ].content = f"{col} ({cur_len}/{max_length}):"
      
  pass # end of input_change

  def form_show(self, **event_args):
    # Forces the browser to scroll directly to the top of your main form container
    # Target the first component inside the panel instead of the whole panel
    components = self.column_panel_1.get_components()
    if components:
      components[0].scroll_into_view()
  pass
  
  def __init__(self, site_id, table_name, data_list, action, page_info, **properties):
    # Set Form properties and Data Bindings.
    self.init_components(**properties)
    # Bind the form_show event
    self.set_event_handler("show", self.form_show)
      
    # Any code you write here will run before the form opens.
    self.site_id = site_id
    Global.table_name = table_name
    
    # Global.site_id is only None when form called from server side (e.g. printing form)
    if Global.site_id is None:
      # initialise some Globals variables for when the function is called from the server side
      Global.site_id = site_id
      Global.action = "View " + table_name.capitalize()
      Global.current_work_area_name = Global.action
      Global.work_area = {}
      Global.work_area[Global.current_work_area_name] = {}
      Global.work_area[Global.current_work_area_name]["data_list"] = data_list
    #else:
      # set table_name to one of "context", "find", from the action Global variable
      #print(Global.table_name)
      #print(Global.work_area[Global.current_work_area_name]["action"])
      #Global.table_name = Global.work_area[Global.current_work_area_name]["action"].split(" ")[1].lower()
      # Global.action.split(" ")[1].rstrip("s").lower()

    action = Global.action.split(" ")[0].lower()
   
    # Inititalize the validator
    self.validator = Validator()

    # we need to find out which table we are dealing with
    self.ws_name.text = Global.current_work_area_name
    self.title.text = "This form is to " + Global.action

    # And then we need to create all the fields based on table information 
    # loop over table columns
    self.field_details = {}
    self.form_fields = {}

    for item in Global.work_area[Global.current_work_area_name]["table_info"]:
      #print(item)
      if Global.table_name == "us": # this if is always false - can be removed
        column_name = item["name"]
        # ignore some columns of system users table
        if column_name in Global.ignore_users_columns:
          continue
        column_type = item["type"]
      else:
        column_name = item["COLUMN_NAME"]
        column_type = item["COLUMN_TYPE"]
     
      # ignore columns with Txt at the end or DBAcontrol
      if column_name.endswith(Global.TX_extension) or column_name in ["DBAcontrol"]:
        continue

      # ---------------------------------------------------------------
      # 0. QUERY table_column_meta_data CONFIGURATION FOR CURRENT FIELD
      # ---------------------------------------------------------------
      has_yaml_config = (
          Global.table_name in Global.table_column_meta_data
          and column_name in Global.table_column_meta_data[Global.table_name]
      )
      yaml_rule = (
          Global.table_column_meta_data[Global.table_name][column_name]
          if has_yaml_config
          else {}
      )
      input_type = yaml_rule.get("type")
      #print(column_name, input_type, column_type)
      # types can be varchar(length),int(length),text,float,double,date
      # type text can be 65535 char so need to be a TextArea, other can be a TextBox
      # create the label (= column/field name) and the input field

      # -----------------------------------------------------------
      # 1. COMPONENT CREATION SWITCH BLOCK
      # -----------------------------------------------------------
      if input_type in ["single_select", "multi_select"]:
        input = Function.create_custom_select_component(
          {**yaml_rule, "name": column_name}
        )
        max_length = 65535 if input_type == "multi_select" else 255

      elif input_type in ["dropdown", "list"]:
        input = DropDown(placeholder=yaml_rule.get("placeholder", column_name))
        input.items = yaml_rule.get("options", [])
        input.include_placeholder = True
        max_length = 255

      elif column_type in ["text","longtext"]:
        max_length = 65535
        if column_name in Global.TextArea_columns:
          # create TextArea input field 
          input = TextArea(placeholder=column_name,tag=column_name)
          input.add_event_handler('change',self.input_change)
          # block keystokes when max_length has reached
          get_dom_node(input).setAttribute("maxlength", str(max_length))
        else:
          # create a Quill input field
          #input = Quill(placeholder=column_name,toolbar=Global.Quill_toolbarOptions)
          input = Quill(toolbar=Global.Quill_toolbarOptions)
          input.tag = column_name
          input.add_event_handler('text_change',self.input_change)

        
      elif column_type == "date":
        input = DatePicker(placeholder=column_name,format="%d-%m-%Y")
        # date type is 10 long
        max_length = 10
        
      elif column_type == "string":
        input = TextBox(placeholder=column_name)
        input.add_event_handler('change',self.input_change)
        max_length = 100
        
      elif column_type in ["bool", "tinyint(1)"]:
        #input = TextBox(placeholder=column_name)
        input = DropDown(items=["True", "False"],placeholder=column_name)
        input.add_event_handler('change',self.input_change)
        max_length = 5
        
      elif column_type == "datetime":
        input = TextBox(placeholder=column_name)
        input.add_event_handler('change',self.input_change)
        max_length = 30
      
      elif Global.table_name in Global.table_column_with_dropdown.keys() and column_name in Global.table_column_with_dropdown[Global.table_name].keys():
      #elif column_name in Global.column_with_dropdown.keys():
        input = DropDown(placeholder=column_name)
        input.add_event_handler('change',self.input_change)
        max_length = 5
        
      else:
        # by default create TextBox fields
        #print(f"TextBox for {column_name}")
        input = TextBox(placeholder=column_name)
        # extract length from type
        match = re.search(r'\d+',column_type)
        max_length = int(match.group()) if match else 10
        if column_type.find("decimal") != -1 or column_type.find("float") != -1 or column_type.find("double") != -1:
          # for these data types (decimal, double, float) add 1 to max_length as length does not take into account the decimal point
          # (nor for negative symbol but that is not applicable for us)
          max_length = max_length + 1
        
        # block keystokes when max_length has reached
        get_dom_node(input).setAttribute("maxlength", str(max_length))
        # add event handler for when input field is changed to update the character count
        input.add_event_handler('change',self.input_change)

      # create input_error label used for validation
      input_error = TextBox(placeholder="Please enter the correct value")
      input_error.visible = False

      # set specific validation checks for the various fields
      if Global.table_name == "us":
        cname = "name"
        prim_key = True if item[cname] == "email" else False
      else:
        cname = "COLUMN_NAME"
        prim_key = True if item["COLUMN_KEY"] == "PRI"  else False
      # if column is Primary Key or a known special column then make it un-editable when action is View or Edit 
      if (
        not (action in ["insert","add"] and Global.table_name == "site" and item[cname] == "SiteId") and 
        ((action == "view") or (action in ["edit"] and prim_key) or
         (action in ["insert"] and item[cname] == "SiteId") or column_name in ["DBAcontrol","RegistrationDate"]) or
        column_name in Global.columns_not_editable
      ):
        #if ((action == "view") or (action in ["edit"] and item["COLUMN_KEY"] == "PRI") or (action in ["insert"] and item["COLUMN_NAME"] == "SiteId") or column_name in ["DBAcontrol","RegistrationDate"]):
        input.enabled = False
        input.background = "#ffffff"

      ################################
      # set input validaton for fields 
      # -----------------------------------------------------------
      # 2. VALIDATION HOOKS
      # -----------------------------------------------------------
      if input_type in ["single_select", "multi_select"]:
        input_error.foreground = "#FF0000"

        def dynamic_select_validator(comp, err_label=input_error, rule=yaml_rule):
          is_valid, msg = Function.validate_custom_select(comp)
          if not is_valid:
            err_label.text = msg or rule.get(
              "error", "Invalid selection"
            )
          return is_valid

        self.validator.require(
          input,
          ["x-change"],
          lambda comp: dynamic_select_validator(comp),
          input_error,
        )

      elif input_type in ["dropdown", "list"]:
        input_error.text = yaml_rule.get(
          "error", "Please choose an option from the list"
        )
        input_error.foreground = "#FF0000"
        self.validator.require(
           input, ["change"], lambda dd: dd.selected_value is not None, input_error
        )

      elif column_name in ["YearEnd","YearStart","Year","ContextYear","SurveyYear"]:
        input_error.text = "Enter a correct year format (-2147483648 to 2147483647)"
        input_error.foreground ="#FF0000"
        # 
        self.validator.require(
          input,
          ['change', 'lost_focus'],
          lambda comp: DataValidation.validate_year(comp.text)[0],
          input_error
        )

      elif column_name == Global.table_name.capitalize()+"Id":
        input_error.text = "You have to enter an Id"
        input_error.foreground ="#FF0000"
        # 
        self.validator.require_text_field(input,input_error)

      elif column_name in ["Email","email"]:
        input_error.text = "You must enter an email address"
        input_error.foreground ="#FF0000"
        self.validator.require(
          input,
          ['change', 'lost_focus'],
          lambda comp: DataValidation.validate_email(comp.text)[0],
          input_error
        )

      elif column_name == "BNGRcentroid":
        input_error.text = "Please enter BNGR coor"
        input_error.foreground ="#FF0000"
        # 
        self.validator.require(
          input,
          ['change', 'lost_focus'],
          lambda comp: DataValidation.validate_BNGRcentroid(comp.text)[0],
          input_error
        )

      elif column_name.endswith("Percentage"):
        input_error.text = "Please enter a percentage value between 0-100 (format 999.999)"
        input_error.foreground ="#FF0000"
        # 
        self.validator.require(
          input,
          ['change', 'lost_focus'],
          lambda comp: DataValidation.validate_percentage(comp.text)[0],
          input_error
        )
      
      elif column_type[:3] == "int":
        input_error.text = "Please enter a valid whole number"
        input_error.foreground ="#FF0000"
        # 
        self.validator.require(
          input,
          ['change', 'lost_focus'],
          lambda comp: DataValidation.validate_integer(comp.text)[0],
          input_error
        )
        #lambda tb: re.fullmatch(r"^$|^\d*$", tb.text),

      elif any(dt in column_type.lower() for dt in ["decimal", "float", "double"]):
        dec_type = re.findall(r'\d+',column_type)
        input_error.text = "Please enter a valid number"
        if dec_type != []:
          input_error.text = "Please enter a valid number in the form " + "x" * (int(dec_type[0]) - int(dec_type[1])) + "." + "x" * int(dec_type[1])

        input_error.foreground ="#FF0000"
        # 
        self.validator.require(
          input,
          ['change','lost_focus'],
          lambda comp, col_type=column_type: DataValidation.validate_decimal("" if comp.text is None else str(comp.text),col_type)[0],
          input_error
        )

      # the follwing are probably no longer required
      elif Global.table_name in Global.table_column_with_list.keys() and column_name in Global.table_column_with_list[Global.table_name].keys():
      #elif column_name in Global.column_with_list.keys():
        # 1. Define your list of allowed words
        allowed_words = Global.table_column_with_list[Global.table_name][column_name]["options"]
        #allowed_words = Global.column_with_list[column_name]["options"]
        # 2. Build the "OR" part of the rgex: 
        choices = r'(?:' + '|'.join(map(re.escape, allowed_words)) + r')'
        # 3. Assemble the full pattern
        # Starts with a choice, followed by zero or more (comma + choice)
        pattern_string = rf'^{choices}(?:\s*,\s*{choices})*$'
        input_error.text = "You must enter a comma separarted list of " + str(allowed_words)
        input_error.foreground ="#FF0000"
        self.validator.require(
          input,
          ['change', 'lost_focus'],
          lambda tb: re.fullmatch(pattern_string, tb.text),
          input_error
        )
      elif Global.table_name in Global.table_column_with_dropdown.keys() and column_name in Global.table_column_with_dropdown[Global.table_name].keys():
      #elif column_name in Global.column_with_dropdown.keys():
        # 1. Define your allowed options for the DropDown
        input.items = Global.table_column_with_dropdown[Global.table_name][column_name]["options"]
        #input.items = Global.column_with_dropdown[column_name]["options"]
        input.include_placeholder = True 
        input.placeholder = Global.table_column_with_dropdown[Global.table_name][column_name]["placeholder"]
        #input.placeholder = Global.column_with_dropdown[column_name]["placeholder"]
        # 2. Configure the error label
        input_error.text = Global.table_column_with_dropdown[Global.table_name][column_name]["error"]
        #input_error.text = Global.column_with_dropdown[column_name]["error"]
        input_error.foreground = "#FF0000"
        # 3. Use the validator to check the selected_value
        self.validator.require(
          input,
          ['change'],
          lambda dd: dd.selected_value is not None,
          input_error
        ) 
      # end of setting validation for fields
      ######################################

      # special case when Field is RegistrationDate: Pre-fill is for Insert and also block edit contents
      cur_len = 0
      if action in ["insert","add"] and column_name == "RegistrationDate":
        # force RegistrationDate
        input.text = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        input.enabled = False
        input.background = "#ffffff"

      # if action is View or Edit then fill all fields
      if action in ["edit","update","view"]:
        raw_data = Global.work_area[Global.current_work_area_name]["data_list"][0][column_name]
        # -----------------------------------------------------------
        # 1. HANDLE CUSTOM SINGLE_SELECT AND MULTI_SELECT FIELDS
        # -----------------------------------------------------------
        if input_type in ["single_select", "multi_select"]:
          ctrl = getattr(input, "tag", None)
          if ctrl:
            is_multi = input_type == "multi_select"

            if is_multi:
              # Multi-select: parse string stored in MariaDB (e.g. "Charcoal, Bone, Special Clay")
              if isinstance(raw_data, str):
                vals = [v.strip() for v in raw_data.split(",") if v.strip()]
              elif isinstance(raw_data, (list, tuple)):
                vals = list(raw_data)
              else:
                vals = []

              predefined_options = [cb.text for cb in ctrl["options_controls"]]
              other_values = []

              # Check standard boxes or collect non-matching values into 'Other'
              for v in vals:
                if v in predefined_options:
                  idx = predefined_options.index(v)
                  ctrl["options_controls"][idx].checked = True
                else:
                  other_values.append(v)

              # If there are values that didn't match standard options, fill 'Other'
              if other_values and ctrl["other_toggle"]:
                ctrl["other_toggle"].checked = True
                ctrl["other_input"].visible = True
                ctrl["other_input"].text = ", ".join(other_values)

              cur_len = (
                len(", ".join(vals))
                if isinstance(raw_data, (str, list))
                else 0
              )

            else:
              # Single-select: raw_data is a single string value
              val = str(raw_data) if raw_data is not None else ""
              predefined_options = [rb.value for rb in ctrl["options_controls"]]

              if val in predefined_options:
                idx = predefined_options.index(val)
                ctrl["options_controls"][idx].selected = True
              elif val and ctrl["other_toggle"]:
                ctrl["other_toggle"].selected = True
                ctrl["other_input"].visible = True
                ctrl["other_input"].text = val

              cur_len = len(val)

          # Handle Read-Only / View mode for custom container controls
          if action == "view":
            # Prevent interaction on the whole container without applying :disabled grey CSS
            #input.get_dom_node().style.pointerEvents = "none"
            input.enabled = False
            for cb_or_rb in ctrl["options_controls"]:
              cb_or_rb.enabled = False
            if ctrl["other_toggle"]:
              ctrl["other_toggle"].enabled = False
            if ctrl["other_input"]:
              ctrl["other_input"].enabled = False

        # -----------------------------------------------------------
        # 2. EXISTING COMPONENT TYPES
        # -----------------------------------------------------------
        elif str(type(input)) == "<class 'anvil_extras.Quill.Quill'>":
          #print(f"Quill data for {column_name} is: {raw_data}")
          # the data from the database is json format so use setContemts(text)
          if raw_data:
            # 1. If it's a JSON string, parse it into a Python dict
            if isinstance(raw_data, str):
              try:
                delta_dict = json.loads(raw_data)
              except json.JSONDecodeError:
                # Fallback if raw text wasn't valid JSON
                delta_dict = {"ops": [{"insert": f"{raw_data}\n"}]}
            else:
              delta_dict = raw_data  # Already a dict
            # 2. Pass the parsed dict to Quill
            input.setContents(delta_dict)
          else:
            # Clear editor if data is None/empty
            input.setContents({"ops": []})
          
          cur_len = 0
          if raw_data is not None:
            cur_len = len(raw_data)
          if action == "view":
            input.enable(False)
            input.background = "#ffffff"
        elif str(type(input)) == "<class 'anvil.DatePicker'>":
          input.date = Global.work_area[Global.current_work_area_name]["data_list"][0][column_name]
        # this next one is probably no longer used
        elif str(type(input)) == "<class 'anvil.DropDown'>":
          input.selected_value = Global.work_area[Global.current_work_area_name]["data_list"][0][column_name]
        else:
          input.text = Global.work_area[Global.current_work_area_name]["data_list"][0][column_name]
          if input.text == "None":
            input.text = ""
            cur_len = 0
          if input.text is not None:
            cur_len = len(input.text)

      if Global.table_name.lower() != "site" and column_name == "SiteId" and action in ["edit","insert","add"]: # pre-set SiteId when]
        input.text = Global.site_id
        #print(input.text)
        if input.text == "None":
          input.text = ""
          cur_len = 0
        if input.text is not None:
          cur_len = len(input.text)

      if Global.table_name.lower() == "site" and column_name == "SiteId" and action in ["insert","add"]:
        # for Table site make sure that SiteId column field is empty when action is insert,add
        input.text = "" 
        cur_len = 0

      # create column header with column_name and column_description in one flowpanel (col_header)
      # -----------------------------------------------------------
      # 3. HEADER AND COMPONENT MOUNTING
      # -----------------------------------------------------------
      col = "&nbsp" if item["IS_NULLABLE"] == "YES" else "*"
      display_label = yaml_rule.get("label", column_name)

      if str(type(input)) in [
        "<class 'anvil_extras.Quill.Quill'>",
        "<class 'anvil.TextBox'>",
        "<class 'anvil.TextArea'>",
      ]:
        col += f"<b>&nbsp{display_label}</b> ({cur_len}/{max_length}):"
      else:
        col += f"<b>&nbsp{display_label}</b>: "

      lab = RichText(
        content=col, font_size=14, tag=column_name, format="restricted_html"
      )
      col_comment = item["COLUMN_COMMENT"]
      col_description = Label(text=col_comment, font_size=14)
      col_header = FlowPanel()
      col_header.add_component(lab)
      col_header.add_component(col_description)

      # Save details for retrieval on submit
      self.form_fields[column_name] = {
        "header": lab,
        "description": col_description,
        "field": input,
        "length": max_length,
        "input_type": input_type,
      }

      if Global.table_name == "dbdiary" or column_name != "DBAcontrol":
        self.column_panel_1.add_component(col_header, full_width_row=True)
        self.column_panel_1.add_component(input, full_width_row=True, spacing_above="small", spacing_below="small")
        self.column_panel_1.add_component(input_error, full_width_row=True)
        
    # endof for loop item in table_info

    # Add a Submit button if Edit or Add action
    if action in ["edit","add","insert"]:     #"Edit Context","Edit Find","Add Context","Add Find"]:
      submit_btn = Button(text="Submit",role="outlined-button")
      submit_btn.add_event_handler("click",self.submit_btn_click)
      self.column_panel_1.add_component(submit_btn)

    # Add a Execute SQL command button if View Query
    if Global.action in ["View Query","View query"]:     
      execute_sql_btn = Button(text="Execute SQL command",role="outlined-button")
      execute_sql_btn.add_event_handler("click",self.execute_sql_btn_click)
      self.column_panel_1.add_component(execute_sql_btn)
      
    # For this work_area form the page_info details are all set to 0; this is for when the server print function calls this form
    Global.work_area[Global.current_work_area_name]["page_info"] = {"page_num": 0, "rows_per_page": 0, "total_rows": 0}
    Global.work_area[Global.current_work_area_name]["self"] = self

    pass # end of init
  
  def execute_sql_btn_click(self, **event_args):
    #print("Execute SQL command button pressed")
    formfields = self.form_fields
    # SQL_command is a <class 'anvil_extras.Quill.Quill'> object as it is a text datatype
    # so needs to get the text with the Quill method getText() -- not any more. Is is now a TextArea type field (TB 2026-10-02)
    # Get QueryId
    query_id_field = formfields.get("QueryId", {}).get("field")
    Global.query_id = str(query_id_field.text) if query_id_field else "0"
    
    # Get SQL Command (Adjust key case if needed: "SQL_command", "SQL_Command", etc.)
    sql_field = formfields.get("SQL_command", {}).get("field")
    
    if str(type(sql_field)) == "<class 'anvil_extras.Quill.Quill'>":
      # just in case SQL_command is a Quill datatype (which it shouldn't be)
      command = str(sql_field.getText()).strip() if sql_field else ""
      #command = str(sql_field.html.strip()) if sql_field else ""

      # 2. Safely retrieve field object regardless of key case
      target_key = next((k for k in formfields.keys() if k.lower() == "sql_command"), None)

      if target_key:
        sql_field = formfields[target_key]['field']
        #print(f"Field object found: {type(sql_field)}")

        # Try standard anvil_extras Quill .text property first
        if hasattr(sql_field, 'text'):
          command = str(sql_field.text).strip()
        elif hasattr(sql_field, 'get_text'):
          command = str(sql_field.get_text()).strip()
        elif hasattr(sql_field, 'getText'):
          command = str(sql_field.getText()).strip()
        else:
          command = ""
      else:
        print("ERROR: 'SQL_command' key was not found in form_fields!")
        command = ""
    elif str(type(sql_field)) == "<class 'anvil.TextArea'>":
      # SQL_command is a TextArea data_type
      command = sql_field.text
    else:
      # SQL_command is a unknown data_type
      command = ""
      
    ###
    # add a check if the SQL_command is a parametarised procedure and then ask for the input values for the parameters
    ###
    
    if command != "":
      msg, data_list, column_order, Global.tmp_table_info = anvil.server.call("execute_sql_command",command)

    else:
      msg = "FAIL: SQL command field is empty."
 
    # Check msg for succes or FAIL
    if msg[0: 4] == "FAIL":
      alert(msg)
    else:
      # SQL command completed successfully and returned a data_list. Create a new TableList workspace
      Global.column_order = column_order
      Global.table_items = data_list
      Global.table_name = "qresult"
      Global.action = "List " + Global.table_name.capitalize()
      if Global.main_form:  # Important to check if the form exists
        # Create new work_area "View Context" and set focus on this new work_area
        Global.main_form.create_new_work_area(Global.action)
      else:
        print("Main form not found!")

    pass # end of execute_sql_btn_click

  def submit_btn_click(self, **event_args):
    """This method is called when the button is clicked"""
    #print("Submit button clicked: ",Global.action)
    action = Global.action.split(" ")[0].lower()
    table_name = Global.action.split(" ")[1].lower()
    self.validator.show_all_errors()
    if self.validator.is_valid():
      # all validated input fields are ok
      row_list = {}
      for col in self.form_fields.items():
        # Add Additional field validation (if needed) before submitting 
        if str(type(col[1]["field"])) == "<class 'anvil_extras.Quill.Quill'>":
          # here we have to store both the Rtf and the Txt values in two fields (FieldRtf and FieldTxt)
          len_extension = len(Global.RT_extension)
          # check if column is a RT datatype
          if col[0].endswith(Global.RT_extension):
            col_name_txt = col[0][:-len_extension] + Global.TX_extension
            # get the clean text contents of the input out field
            row_list[col_name_txt] = col[1]["field"].getText().strip()
            if row_list[col_name_txt] == "\n":
              row_list[col_name_txt] = ""
            # now get the input as html (to be reviewed). Maybe just keep it as Delta format (JSON) is safer
            # just use the quill.content method and also no need to use the clean_quill_regex
            #row_list[col[0]] = Function.clean_quill_regex(col[1]["field"].get_html())
            # just use the json.dump method for the quil getContents()
            #row_list[col[0]] = json.dumps(col[1]["field"].getContents())
            row_list[col[0]] = Function.convert_quill_to_python(col[1]["field"])

          else:
            # text field is not an RT datatype, so just get the plain clean text
            row_list[col[0]] = col[1]["field"].getText().strip()
            
        elif str(type(col[1]["field"])) == "<class 'anvil.DatePicker'>":
          row_list[col[0]] = col[1]["field"].date
          
        elif str(type(col[1]["field"])) == "<class 'anvil.DropDown'>":
          row_list[col[0]] = col[1]["field"].selected_value
          
        elif str(type(col[1]["field"])) in ["<class 'anvil.TextBox'>","<class 'anvil.TextArea'>"]:
          row_list[col[0]] = col[1]["field"].text

        # set empty fields to None
        if row_list[col[0]] in ["","\n"," "]:
          row_list[col[0]] = None
      #
      del_workspace = False
      if action in ["add","insert"]:
        ret = anvil.server.call("row_insert",Global.site_id,table_name,row_list)
        # if success then goto list contexts
        if ret[:2] == "OK":
          msg = "Row has been successfully inserted to the database."
          # if a site has been added, update the site selection dropdown
          del_workspace = True
          if table_name == "site":
            Global.site_options = FunctionsB.set_select_site_dropdown_options() 
            Global.select_site_dropdown.items = Global.site_options.keys()
          # update Site Summary
          Function.update_db_summary()
          #db_summary = anvil.server.call("db_get_summary",Global.site_id)
          #Global.main_form.site_summary.visible = True
          #Global.main_form.site_summary.items = db_summary
        else:
          msg = "Row has not been inserted to the database, because of " + ret
      elif action in ["edit","update"]:
        ret = anvil.server.call("row_update",Global.site_id,table_name,row_list)
        # if success then goto list contexts
        if ret[:2] == "OK":
          msg = "Row has been successfully updated in the database."
          del_workspace = True
        else:
          msg = "Row has not been updated in the database, because of " + ret
      else:
        msg = "Unknown action: " + action
      alert(content=msg)
      if del_workspace:
        Function.delete_workspace(Global.current_work_area_name)
    else:
      self.validator.show_all_errors()
      alert("There are errors in the form input")

    pass # end of submit_btn_click

  