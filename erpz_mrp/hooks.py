app_name = "erpz_mrp"
app_title = "ERPZ MRP"
app_publisher = "ERPZ"
app_description = "MRP - Planejamento de Necessidades de Materiais Multiempresa"
app_email = "dev@erpz.io"
app_license = "mit"

# Apps
# ------------------

# Installation & Migrations
after_install = "erpz_mrp.setup.setup_mrp_custom_fields"
after_migrate = "erpz_mrp.setup.setup_mrp_custom_fields"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/erpz_mrp/css/erpz_mrp.css"
# app_include_js = "/assets/erpz_mrp/js/erpz_mrp.js"

# DocType List JS
doctype_list_js = {
	"MRP Result": "erpz_mrp/doctype/mrp_result/mrp_result_list.js"
}
