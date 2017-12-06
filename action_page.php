<html>
<body>

<?php

$myfile = fopen("newfile.txt", "w") or die("Unable to open file!");
$txt = $_GET["username"];
fwrite($myfile, $txt);
fclose($myfile);

 ?php>

</body>
</html>
